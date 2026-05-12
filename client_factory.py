"""
Client Factory — automated deployment engine for Laval Digital.

Creates a new client's static website and isolated tenant database
with a single click from the admin panel.

Pipeline:
  1. Validate config
  2. Generate subdomain
  3. Create tenant database
  4. Clone template repo
  5. Inject brand into HTML
  6. Deploy Nginx server block
  7. Provision SSL via certbot
  8. Send welcome email
"""

import os
import re
import sys
import json
import logging
import shutil
import smtplib
import subprocess
import threading
import unicodedata
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.tenant_manager import TenantManager

logger = logging.getLogger(__name__)

NICHE_CONFIG = {
    "plumber": {"primary": "#1a3a5c", "accent": "#D42B2B", "hero_img": "plumbing-bg.jpg"},
    "electrician": {"primary": "#1a3a5c", "accent": "#ffd166", "hero_img": "electrical-bg.jpg"},
    "landscaper": {"primary": "#2d5a27", "accent": "#f4a261", "hero_img": "landscaping-bg.jpg"},
    "roofer": {"primary": "#4a4a4a", "accent": "#e63946", "hero_img": "roofing-bg.jpg"},
    "hvac": {"primary": "#003049", "accent": "#fcbf49", "hero_img": "hvac-bg.jpg"},
    "cleaner": {"primary": "#264653", "accent": "#2a9d8f", "hero_img": "cleaning-bg.jpg"},
    "painter": {"primary": "#3d405b", "accent": "#e07a5f", "hero_img": "painting-bg.jpg"},
}

REQUIRED_FIELDS = [
    "business_name", "client_email", "phone", "city", "niche", "services",
]


class ClientFactory:
    """Automated deployment engine for Laval Digital client sites.

    Orchestrates a 7-station pipeline that validates input, generates
    a subdomain, provisions a tenant database, clones and customises
    the template site, deploys behind Nginx with SSL, and sends a
    welcome email.

    Thread-safe: uses a ``threading.Lock`` so ``deploy()`` can be called
    concurrently from the admin panel without race conditions.
    """

    def __init__(self) -> None:
        """Initialise paths, tenant manager, and logging."""
        self.template_repo = "https://github.com/shogodel/laval-digital.git"
        self.deploy_base = Path("/var/www/clients")
        self.nginx_available = Path("/etc/nginx/sites-available")
        self.nginx_enabled = Path("/etc/nginx/sites-enabled")
        self.tenant_manager = TenantManager()
        self.log_file = Path("logs/client_factory.log")
        self._lock = threading.Lock()

        self.deploy_base.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(str(self.log_file))
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(file_handler)

    # ------------------------------------------------------------------
    # Station 1: Validate config
    # ------------------------------------------------------------------

    @staticmethod
    def validate_config(config: dict) -> list:
        """Return a list of missing or empty required field names.

        Args:
            config: Raw configuration dict from the admin panel.

        Returns:
            List of field names that are missing or empty.
        """
        missing = []
        for field in REQUIRED_FIELDS:
            if field not in config or not config[field]:
                missing.append(field)

        niche = config.get("niche", "")
        if niche and niche not in NICHE_CONFIG:
            missing.append(f"niche '{niche}' (unsupported — must be one of: {', '.join(NICHE_CONFIG)})")

        services = config.get("services")
        if services is not None and not isinstance(services, list):
            missing.append("services (must be a list)")

        return missing

    # ------------------------------------------------------------------
    # Station 2: Generate subdomain
    # ------------------------------------------------------------------

    @staticmethod
    def generate_subdomain(business_name: str) -> str:
        """Convert a business name to a URL-safe subdomain.

        Examples:
            "Mike's Plumbing" → ``mikes-plumbing``
            "Laval Électrique" → ``laval-electrique``

        Rules:
            - Lowercase
            - Remove accents / diacritics
            - Strip characters that are not ``[a-z0-9 -]``
            - Collapse consecutive hyphens
            - Strip leading / trailing hyphens
        """
        name = business_name.strip()

        # Decompose unicode and drop combining marks (accents)
        name = unicodedata.normalize("NFKD", name)
        name = name.encode("ascii", "ignore").decode("ascii")

        # Lowercase after decomposition (NFKD may re-introduce capitals)
        name = name.lower()

        # Replace apostrophes and underscores with nothing
        name = name.replace("'", "").replace("’", "").replace("_", "")

        # Replace anything that is not a letter, digit, space, or hyphen
        name = re.sub(r"[^a-z0-9\s-]", "", name)

        # Spaces and runs of spaces → single hyphen
        name = re.sub(r"\s+", "-", name)

        # Collapse multiple hyphens
        name = re.sub(r"-+", "-", name)

        # Strip leading / trailing hyphens
        name = name.strip("-")

        return name if name else "client"

    # ------------------------------------------------------------------
    # Station 3: Create tenant database
    # ------------------------------------------------------------------

    def create_tenant(self, config: dict, subdomain: str) -> str:
        """Create the tenant database and return the tenant_id.

        Args:
            config: Client configuration (used for seeding client_details).
            subdomain: URL-safe subdomain that doubles as tenant_id.

        Returns:
            The tenant_id (same as subdomain).
        """
        tenant_id = subdomain
        db_path = self.tenant_manager.create_tenant_database(tenant_id, "direct")
        logger.info("Created tenant database for %s: %s", subdomain, db_path)

        # Seed the client_details and payment records
        conn = self.tenant_manager.get_connection(tenant_id)
        cursor = conn.cursor()

        package = config.get("package", "")
        price = config.get("price", 0)
        affiliate = config.get("affiliate_code", "")

        cursor.execute(
            """
            INSERT OR REPLACE INTO client_details
                (business_name, contact_name, email, phone, city, services,
                 niche, package, price, affiliate_code, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config.get("business_name", ""),
                config.get("contact_name", ""),
                config.get("client_email", ""),
                config.get("phone", ""),
                config.get("city", ""),
                json.dumps(config.get("services", [])),
                config.get("niche", ""),
                package,
                price,
                affiliate,
                datetime.datetime.utcnow().isoformat(),
            ),
        )

        # Seed payment schedule if provided
        schedule = config.get("payment_schedule", {})
        if schedule:
            for i, (key, amount) in enumerate(schedule.items(), start=1):
                cursor.execute(
                    """
                    INSERT INTO payments (installment_number, amount, paid)
                    VALUES (?, ?, 0)
                    """,
                    (i, amount),
                )

        conn.commit()
        logger.info(
            "Seeded client_details and %d payment records for tenant %s",
            len(schedule),
            tenant_id,
        )
        return tenant_id

    # ------------------------------------------------------------------
    # Station 4: Clone template
    # ------------------------------------------------------------------

    def clone_template(self, subdomain: str) -> Path:
        """Clone the GitHub template into ``/var/www/clients/<subdomain>``.

        If the target directory already exists it is removed first.

        Args:
            subdomain: The client subdomain (directory name).

        Returns:
            Path to the cloned site directory.

        Raises:
            subprocess.CalledProcessError: If ``git clone`` fails.
        """
        site_path = self.deploy_base / subdomain
        if site_path.exists():
            shutil.rmtree(site_path)
            logger.info("Removed existing directory: %s", site_path)

        subprocess.run(
            ["git", "clone", "--depth", "1", self.template_repo, str(site_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("Cloned template repo into %s", site_path)
        return site_path

    # ------------------------------------------------------------------
    # Station 5: Inject brand
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_logo(site_path: Path) -> str:
        """Detect which logo file exists in the static directory."""
        for ext in ("png", "svg"):
            candidate = site_path / "static" / f"logo_custom.{ext}"
            if candidate.exists():
                return f"logo_custom.{ext}"
        return "logo.svg"

    def inject_brand(self, config: dict, site_path: Path) -> None:
        """Replace all brand placeholders in HTML files under *site_path*.

        Walks every ``.html`` file and performs:

        1. Flask ``{{ url_for('static', filename='...') }}`` → ``static/...``
        2. Flask ``{{ url_for('static', filename=VAR) }}`` where ``VAR`` is
           a known variable name.
        3. Known Jinja2 variables (``logo_file``, ``now``, …).
        4. Custom business placeholders:
           ``{{ business_name }}``, ``{{ city }}``, ``{{ phone }}``,
           ``{{ client_email }}``, ``{{ primary_color }}``,
           ``{{ accent_color }}``, ``{{ hero_background }}``,
           ``{{ package_name }}``, ``{{ services }}``.
        5. Injects a ``<style>`` block with the niche's CSS variables.
        6. Removes any leftover Jinja2 ``{{ ... }}`` and ``{% ... %}``
           tags so the page renders cleanly as static HTML.

        Args:
            config: Client configuration dict.
            site_path: Root of the cloned site.
        """
        niche = config.get("niche", "plumber")
        colors = NICHE_CONFIG.get(niche, NICHE_CONFIG["plumber"])

        # Build services HTML
        services = config.get("services", [])
        services_html = "\n".join(f"            <li>{s}</li>" for s in services)

        # Resolve logo
        logo_file = self._resolve_logo(site_path)

        # Build replacement map (processed in order)
        replacements = {
            "{{ business_name }}": config.get("business_name", ""),
            "{{ city }}": config.get("city", ""),
            "{{ phone }}": config.get("phone", ""),
            "{{ client_email }}": config.get("client_email", ""),
            "{{ primary_color }}": colors["primary"],
            "{{ accent_color }}": colors["accent"],
            "{{ hero_background }}": colors["hero_img"],
            "{{ package_name }}": config.get("package", ""),
            "{{ services }}": services_html,
        }

        # Regex to find existing :root { ... } blocks in <style>
        root_block_re = re.compile(
            r"(:root\s*\{)([^}]*)(\})", re.IGNORECASE | re.DOTALL
        )

        url_for_re = re.compile(r"\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}")
        url_for_var_re = re.compile(r"\{\{\s*url_for\('static',\s*filename=(\w+)\)\s*\}\}")

        count = 0
        for html_file in sorted(site_path.rglob("*.html")):
            original = html_file.read_text(encoding="utf-8")
            content = original

            # 1. {{ url_for('static', filename='...') }} → static/...
            content = url_for_re.sub(r"static/\1", content)

            # 2. {{ url_for('static', filename=VAR) }} where VAR is known
            def _replace_var(m: re.Match) -> str:
                var = m.group(1)
                if var == "logo_file":
                    return f"static/{logo_file}"
                return f"static/{var}"
            content = url_for_var_re.sub(_replace_var, content)

            # 3. Known Jinja2 variables
            content = content.replace("{{ logo_file }}", logo_file)

            # 4. Custom placeholders
            for placeholder, value in replacements.items():
                content = content.replace(placeholder, value)

            # 5. Replace existing :root { } CSS variable values with niche colors
            def _replace_root(m: re.Match) -> str:
                block = m.group(2)
                block = re.sub(
                    r"--primary\s*:\s*[^;]+;",
                    f"--primary: {colors['primary']};",
                    block,
                )
                block = re.sub(
                    r"--accent\s*:\s*[^;]+;",
                    f"--accent: {colors['accent']};",
                    block,
                )
                return m.group(1) + block + m.group(3)
            content = root_block_re.sub(_replace_root, content)

            # 6. Remove any leftover Jinja2 {{ ... }} or {% ... %}
            content = re.sub(r"\{\{.*?\}\}", "", content, flags=re.DOTALL)
            content = re.sub(r"\{%-?\s*.*?\s*-?%\}", "", content, flags=re.DOTALL)
            # Clean up blank lines that may result from removal
            content = re.sub(r"\n\s*\n\s*\n+", "\n\n", content)

            if content != original:
                html_file.write_text(content, encoding="utf-8")
                count += 1
                logger.debug("Injected brand into %s", html_file)

        logger.info(
            "Brand injection complete — updated %d HTML files for %s",
            count,
            config.get("business_name", "?"),
        )

    # ------------------------------------------------------------------
    # Station 6: Deploy Nginx
    # ------------------------------------------------------------------

    def deploy_nginx(self, subdomain: str, site_path: Path, business_name: str = "") -> bool:
        """Create a production-grade NGINX server block for a client subdomain.

        Features:
        - Dedicated access and error logs per client
        - Security headers (X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
        - Custom 404 error page with business branding
        - robots.txt for search engine indexing
        - Proper NGINX configuration testing before reload

        Args:
            subdomain: The client's subdomain (e.g., "mikes-plumbing")
            site_path: Absolute path to the client's deployed site files
            business_name: The client's business name for custom error pages

        Returns:
            True if deployment succeeded, False otherwise
        """
        domain = f"{subdomain}.lavaldigital.ca"
        config_path = self.nginx_available / subdomain
        enabled_path = self.nginx_enabled / subdomain

        # Step 1: Create robots.txt
        robots_path = site_path / "robots.txt"
        robots_path.write_text("User-agent: *\nAllow: /\n")
        logger.info("Created robots.txt for %s", subdomain)

        # Step 2: Create custom 404 page
        error_404_path = site_path / "404.html"
        error_404_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page Not Found — {business_name or domain}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            text-align: center;
            padding-top: 80px;
            color: #374151;
            background: #f9fafb;
            min-height: 100vh;
            margin: 0;
        }}
        h1 {{ font-size: 2rem; color: #111827; margin-bottom: 16px; }}
        p {{ font-size: 1.1rem; color: #6b7280; margin-bottom: 24px; }}
        a {{ color: #D42B2B; text-decoration: none; font-weight: 600; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>Oops! Page Not Found</h1>
    <p>Sorry, the page you're looking for doesn't exist.</p>
    <p><a href="/">Return to {business_name or 'Home'}</a></p>
</body>
</html>"""
        error_404_path.write_text(error_404_content, encoding="utf-8")
        logger.info("Created custom 404 page for %s", subdomain)

        # Step 3: Create NGINX server block configuration
        log_dir = Path("/var/log/nginx")
        log_dir.mkdir(parents=True, exist_ok=True)

        nginx_config = f"""# Laval Digital — Client Site: {business_name or subdomain}
# Auto-generated by Client Factory — Do not edit manually

server {{
    listen 80;
    listen [::]:80;

    server_name {domain};
    root {site_path};
    index home.html index.html;

    # Dedicated logging per client
    access_log /var/log/nginx/{subdomain}.access.log;
    error_log /var/log/nginx/{subdomain}.error.log;

    # Custom error pages
    error_page 404 /404.html;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Main location block
    location / {{
        try_files $uri $uri/ =404;
    }}

    # Static asset caching (images, CSS, JS, fonts)
    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}

    # Deny access to hidden files
    location ~ /\\. {{
        deny all;
    }}
}}
"""

        # Step 4: Write the NGINX config file
        config_path.write_text(nginx_config, encoding="utf-8")
        logger.info("Written NGINX config for %s", domain)

        # Step 5: Create symlink to enable the site
        if enabled_path.exists():
            enabled_path.unlink()
        enabled_path.symlink_to(config_path)
        logger.info("Enabled site: %s", domain)

        # Step 6: Test NGINX configuration
        try:
            result = subprocess.run(
                ["nginx", "-t"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("NGINX configuration test passed: %s", result.stdout.strip())
        except subprocess.CalledProcessError as e:
            logger.error("NGINX configuration test failed: %s", e.stderr)
            # Remove the broken symlink to prevent NGINX from failing on reload
            if enabled_path.exists():
                enabled_path.unlink()
            return False

        # Step 7: Reload NGINX
        try:
            subprocess.run(
                ["systemctl", "reload", "nginx"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("NGINX reloaded — %s is now live", domain)
        except subprocess.CalledProcessError as e:
            logger.error("NGINX reload failed: %s", e.stderr)
            return False

        return True

    # ------------------------------------------------------------------
    # Station 7: Provision SSL
    # ------------------------------------------------------------------

    def provision_ssl(self, subdomain: str, base_domain: str = "lavaldigital.ca") -> bool:
        """Run certbot to obtain a Let's Encrypt SSL certificate.

        Uses the ``--nginx`` authenticator non-interactively.

        .. note::
           If certbot is not installed or the domain does not resolve yet,
           the failure is logged but **not** fatal — the site can still be
           served over HTTP.

        Args:
            subdomain: Client subdomain.
            base_domain: Base domain to append (default ``lavaldigital.ca``).

        Returns:
            ``True`` if the certificate was obtained, ``False`` otherwise.
        """
        domain = f"{subdomain}.{base_domain}"

        if not shutil.which("certbot"):
            logger.warning("certbot not installed — SSL provisioning skipped for %s", domain)
            return False

        try:
            result = subprocess.run(
                [
                    "certbot", "--nginx", "-d", domain,
                    "--non-interactive", "--agree-tos",
                    "-m", "lavaldigital@gmail.com",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                logger.info("SSL certificate provisioned for %s", domain)
                return True
            logger.warning(
                "certbot returned %d for %s:\n%s",
                result.returncode, domain, result.stderr,
            )
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"certbot failed for {domain}: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("certbot timed out for %s — skipping SSL", domain)
            return False
        except Exception as e:
            logger.warning("SSL provisioning failed for %s: %s", domain, e)
            return False

    # ------------------------------------------------------------------
    # Station 8: Send welcome email
    # ------------------------------------------------------------------

    def send_welcome_email(self, config: dict, subdomain: str) -> bool:
        """Send a welcome email to the client via SMTP.

        Reads SMTP credentials from environment variables:

        - ``SMTP_HOST`` (default ``smtp.gmail.com``)
        - ``SMTP_PORT`` (default ``587``)
        - ``SMTP_USERNAME``
        - ``SMTP_PASSWORD``
        - ``SMTP_FROM`` (default ``lavaldigital@gmail.com``)

        Args:
            config: Client configuration dict.
            subdomain: Client subdomain.

        Returns:
            ``True`` if the email was sent, ``False`` on failure.
        """
        contact_name = config.get("contact_name", config.get("business_name", "there"))
        domain = f"{subdomain}.lavaldigital.ca"
        site_url = f"https://{domain}"
        admin_url = f"https://lavaldigital.ca/admin"

        subject = f"Your AI-Powered Website is Live! 🚀"
        body = f"""Hi {contact_name},

Great news — your new AI-powered website is live!

🌐 Your Website: {site_url}
🛠 Admin Panel: {admin_url}

Your site comes with:
• Automated SEO & local search optimization
• AI-powered social media content
• Lead capture & follow-up automation
• 24/7 monitoring & monthly performance reports

Next Steps:
1. Visit your site and check out the design
2. Log into the admin panel to customize your agents
3. Your AI marketing team starts working immediately

Need help? Reply to this email or call us anytime.

Welcome to the Laval Digital family!

—
Laval Digital Team
lavaldigital@gmail.com
"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = os.getenv("SMTP_FROM", "lavaldigital@gmail.com")
        msg["To"] = config.get("client_email", "")
        msg.attach(MIMEText(body, "plain", "utf-8"))

        client_email = config.get("client_email", "")
        if not client_email:
            logger.error("Cannot send welcome email: no client_email in config")
            return False

        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USERNAME", "")
        smtp_pass = os.getenv("SMTP_PASSWORD", "")

        if not smtp_user or not smtp_pass:
            logger.warning(
                "SMTP credentials not configured — skipping welcome email to %s",
                client_email,
            )
            return False

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info("Welcome email sent to %s", client_email)
            return True
        except Exception as e:
            logger.error("Failed to send welcome email to %s: %s", client_email, e)
            return False

    # ------------------------------------------------------------------
    # Pipeline: deploy
    # ------------------------------------------------------------------

    def deploy(self, config: dict) -> dict:
        """Run the full deployment pipeline.

        Each station is wrapped in try/except so that a failure at any
        point returns a structured error dict rather than raising.

        Args:
            config: Client configuration dict.

        Returns:
            Dict with keys:
            - ``success`` (bool)
            - ``subdomain`` (str)
            - ``url`` (str)
            - ``admin_url`` (str)
            - ``tenant_id`` (str or None)
            - ``error`` (str or None)
        """
        with self._lock:
            logger.info("=" * 60)
            logger.info("Starting deployment for: %s", config.get("business_name", "?"))
            logger.info("=" * 60)

            result = {
                "success": False,
                "subdomain": "",
                "url": "",
                "admin_url": "",
                "tenant_id": None,
                "error": None,
            }

            # ---- Station 1: Validate ---------------------------------
            missing = self.validate_config(config)
            if missing:
                msg = f"Missing or invalid fields: {', '.join(missing)}"
                logger.error("Validation failed: %s", msg)
                result["error"] = msg
                return result

            # ---- Station 2: Subdomain --------------------------------
            try:
                subdomain = self.generate_subdomain(config["business_name"])
                result["subdomain"] = subdomain
                result["url"] = f"https://{subdomain}.lavaldigital.ca"
                result["admin_url"] = f"https://lavaldigital.ca/admin"
                logger.info("Generated subdomain: %s", subdomain)
            except Exception as e:
                msg = f"Subdomain generation failed: {e}"
                logger.error(msg)
                result["error"] = msg
                return result

            # ---- Station 3: Tenant DB --------------------------------
            try:
                tenant_id = self.create_tenant(config, subdomain)
                result["tenant_id"] = tenant_id
            except Exception as e:
                msg = f"Tenant database creation failed: {e}"
                logger.error(msg)
                result["error"] = msg
                return result

            # ---- Station 4: Clone template ---------------------------
            try:
                site_path = self.clone_template(subdomain)
            except Exception as e:
                msg = f"Template clone failed: {e}"
                logger.error(msg)
                result["error"] = msg
                return result

            # ---- Station 5: Inject brand -----------------------------
            try:
                self.inject_brand(config, site_path)
            except Exception as e:
                msg = f"Brand injection failed: {e}"
                logger.error(msg)
                result["error"] = msg
                return result

            # ---- Station 6: Nginx ------------------------------------
            try:
                nginx_ok = self.deploy_nginx(subdomain, site_path, config.get("business_name", ""))
                if not nginx_ok:
                    msg = "Nginx configuration failed"
                    logger.error(msg)
                    result["error"] = msg
                    return result
            except Exception as e:
                msg = f"Nginx deployment failed: {e}"
                logger.error(msg)
                result["error"] = msg
                return result

            # ---- Station 7: SSL (non-fatal) --------------------------
            try:
                self.provision_ssl(subdomain)
            except Exception as e:
                logger.warning("SSL provisioning failed (non-fatal): %s", e)

            # ---- Station 8: Welcome email (non-fatal) ----------------
            try:
                self.send_welcome_email(config, subdomain)
            except Exception as e:
                logger.warning("Welcome email failed (non-fatal): %s", e)

            result["success"] = True
            logger.info(
                "Deployment complete for %s → %s",
                config["business_name"],
                result["url"],
            )
            return result


# ------------------------------------------------------------------ #
# CLI test
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    factory = ClientFactory()

    sample_config = {
        "business_name": "Mike's Plumbing",
        "contact_name": "Mike Tremblay",
        "client_email": "mike@mikesplumbing.ca",
        "phone": "450-555-1234",
        "city": "Laval",
        "niche": "plumber",
        "services": ["Emergency Repairs", "Drain Cleaning", "Water Heaters"],
        "package": "growth_suite",
        "price": 12000,
        "affiliate_code": "MIKE15",
        "payment_schedule": {
            "deposit": 3600,
            "installment_2": 4200,
            "installment_3": 4200,
        },
    }

    # Dry-run: exercise non-destructive methods
    print("=== Validation ===")
    missing = factory.validate_config(sample_config)
    print(f"  Missing fields: {missing if missing else 'None — config is valid'}")

    print("\n=== Subdomain ===")
    sub = factory.generate_subdomain(sample_config["business_name"])
    print(f"  {sample_config['business_name']!r} → {sub!r}")

    print("\n=== Edge-case subdomains ===")
    for name in ["Laval Électrique", "   ", "O'Brien & Sons", "Café № 5"]:
        result = factory.generate_subdomain(name)
        print(f"  {name!r} → {result!r}")

    print("\nTo run a full deployment:")
    print("  python client_factory.py --deploy")
    print("")

    if "--deploy" in sys.argv:
        print("Running full deployment pipeline...")
        result = factory.deploy(sample_config)
        print(f"\nResult: {json.dumps(result, indent=2)}")
