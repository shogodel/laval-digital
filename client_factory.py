"""
Client Factory — automated deployment pipeline for Laval Digital.

Architecture
------------
A pluggable :class:`Pipeline <core.pipeline.Pipeline>` of
:class:`Station <core.pipeline.Station>` instances.  Each station
performs one step (validate, subdomain, tenant DB, clone, brand injection,
Nginx, SSL, email).  Stations are declared at module level in
:data:`STATIONS` and can be added / removed / reordered without touching
the core loop.

If any station fails, all previously completed stations are rolled back in
reverse order.

Brand colours, hero images, and template URLs are loaded from
``config/niches.json`` and ``config/templates.json`` — no code changes
needed to add a new niche.

Post-deployment hooks fire events on the global :class:`EventBus` so the
real-time dashboard can display deployment activity.

Async deployments store their status in :data:`_deploy_status` (an
in-memory dict keyed by deployment ID) so the admin panel can poll
progress.
"""

import json
import logging
import os
import re
import shutil
import smtplib
import subprocess
import threading
import unicodedata
import uuid
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, Undefined

from core.pipeline import Pipeline, PipelineError, Station
from core.tenant_manager import TenantManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent / "config"

_NICHES: Dict[str, Any] = {}
_TEMPLATES: Dict[str, str] = {}


def _load_configs() -> None:
    global _NICHES, _TEMPLATES
    niches_path = _CONFIG_DIR / "niches.json"
    templates_path = _CONFIG_DIR / "templates.json"
    if niches_path.exists():
        _NICHES = json.loads(niches_path.read_text(encoding="utf-8"))
    if templates_path.exists():
        _TEMPLATES = json.loads(templates_path.read_text(encoding="utf-8"))


_load_configs()

REQUIRED_FIELDS = [
    "business_name", "client_email", "phone", "city", "niche", "services",
]

DEPLOY_BASE = Path("/var/www/clients")
NGINX_AVAILABLE = Path("/etc/nginx/sites-available")
NGINX_ENABLED = Path("/etc/nginx/sites-enabled")
LOG_FILE = Path("logs/client_factory.log")

# In-memory async deployment statuses
_deploy_status: Dict[str, Dict[str, Any]] = {}
_deploy_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Station: Validate
# ---------------------------------------------------------------------------


class ValidateStation(Station):
    def __init__(self) -> None:
        super().__init__("validate")

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        missing = []
        for field in REQUIRED_FIELDS:
            if field not in config or not config[field]:
                missing.append(field)
        niche = config.get("niche", "")
        if niche and niche not in _NICHES:
            missing.append(
                f"niche '{niche}' (unsupported — must be one of: {', '.join(_NICHES)})"
            )
        services = config.get("services")
        if services is not None and not isinstance(services, list):
            missing.append("services (must be a list)")
        if missing:
            raise PipelineError(f"Missing or invalid fields: {', '.join(missing)}")

    def rollback(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        pass  # nothing to undo


# ---------------------------------------------------------------------------
# Station: Subdomain
# ---------------------------------------------------------------------------


class SubdomainStation(Station):
    def __init__(self) -> None:
        super().__init__("subdomain")

    @staticmethod
    def generate(name: str) -> str:
        name = name.strip()
        name = unicodedata.normalize("NFKD", name)
        name = name.encode("ascii", "ignore").decode("ascii")
        name = name.lower()
        name = name.replace("'", "").replace("’", "").replace("_", "")
        name = re.sub(r"[^a-z0-9\s-]", "", name)
        name = re.sub(r"\s+", "-", name)
        name = re.sub(r"-+", "-", name)
        name = name.strip("-")
        return name if name else "client"

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        subdomain = self.generate(config["business_name"])
        context["subdomain"] = subdomain
        context["domain"] = f"{subdomain}.lavaldigital.ca"
        context["site_url"] = f"https://{context['domain']}"


# ---------------------------------------------------------------------------
# Station: Tenant database
# ---------------------------------------------------------------------------


class TenantStation(Station):
    def __init__(self) -> None:
        super().__init__("tenant")
        self._tm = TenantManager()

    def _insert_seeds(self, config: Dict[str, Any], subdomain: str) -> None:
        conn = self._tm.get_connection(subdomain)
        cursor = conn.cursor()
        package = config.get("package", "")
        price = config.get("price", 0)
        affiliate = config.get("affiliate_code", "")
        cursor.execute(
            """INSERT OR REPLACE INTO client_details
               (business_name, contact_name, email, phone, city, services,
                niche, package, price, affiliate_code, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                config.get("business_name", ""),
                config.get("contact_name", ""),
                config.get("client_email", ""),
                config.get("phone", ""),
                config.get("city", ""),
                json.dumps(config.get("services", [])),
                config.get("niche", ""),
                package, price, affiliate,
                datetime.datetime.utcnow().isoformat(),
            ),
        )
        schedule = config.get("payment_schedule", {})
        for i, (key, amount) in enumerate(schedule.items(), start=1):
            cursor.execute(
                "INSERT INTO payments (installment_number, amount, paid) VALUES (?, ?, 0)",
                (i, amount),
            )
        conn.commit()

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        subdomain = context["subdomain"]
        db_path = self._tm.create_tenant_database(subdomain, "direct")
        context["tenant_db_path"] = str(db_path)
        self._insert_seeds(config, subdomain)

    def rollback(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        subdomain = context.get("subdomain")
        if subdomain:
            self._tm.delete_tenant(subdomain, "direct")


# ---------------------------------------------------------------------------
# Station: Clone template
# ---------------------------------------------------------------------------


class CloneStation(Station):
    def __init__(self) -> None:
        super().__init__("clone")

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        subdomain = context["subdomain"]
        niche = config.get("niche", "")
        repo_url = _TEMPLATES.get(niche) or _TEMPLATES.get("_default", "")
        site_path = DEPLOY_BASE / subdomain
        if site_path.exists():
            shutil.rmtree(site_path)
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(site_path)],
            check=True, capture_output=True, text=True,
        )
        context["site_path"] = site_path
        context["repo_url"] = repo_url

    def rollback(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        site_path = context.get("site_path")
        if site_path and site_path.exists():
            shutil.rmtree(site_path)


# ---------------------------------------------------------------------------
# Station: Brand injection (Jinja2 rendering)
# ---------------------------------------------------------------------------


class BrandStation(Station):
    def __init__(self) -> None:
        super().__init__("brand")

    @staticmethod
    def _resolve_logo(site_path: Path) -> str:
        for ext in ("png", "svg"):
            candidate = site_path / "static" / f"logo_custom.{ext}"
            if candidate.exists():
                return f"logo_custom.{ext}"
        return "logo.svg"

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        site_path: Path = context["site_path"]
        niche = config.get("niche", "plumber")
        colors = _NICHES.get(niche, _NICHES.get("plumber", {}))
        services = config.get("services", [])
        services_html = "\n".join(f"            <li>{s}</li>" for s in services)
        logo_file = self._resolve_logo(site_path)

        template_vars = {
            "business_name": config.get("business_name", ""),
            "city": config.get("city", ""),
            "phone": config.get("phone", ""),
            "client_email": config.get("client_email", ""),
            "primary_color": colors.get("primary", "#1a3a5c"),
            "accent_color": colors.get("accent", "#D42B2B"),
            "hero_background": colors.get("hero_img", "plumbing-bg.jpg"),
            "package_name": config.get("package", ""),
            "services": services_html,
            "logo_file": logo_file,
        }

        env = Environment(
            loader=FileSystemLoader(str(site_path)),
            autoescape=False,
            undefined=Undefined,
        )

        count = 0
        for html_file in sorted(site_path.rglob("*.html")):
            try:
                raw = html_file.read_text(encoding="utf-8")
                preprocessed = self._preprocess_flask_vars(raw)
                rendered = env.from_string(preprocessed).render(**template_vars)
                cleaned = self._clean_jinja2(rendered)
                if cleaned != raw:
                    html_file.write_text(cleaned, encoding="utf-8")
                    count += 1
            except Exception as e:
                logger.debug("Brand injection fallback for %s: %s", html_file, e)
                raw = html_file.read_text(encoding="utf-8")
                cleaned = self._clean_jinja2(raw)
                if cleaned != raw:
                    html_file.write_text(cleaned, encoding="utf-8")
                    count += 1
        logger.info("Brand injection: updated %d HTML files", count)
        context["branded_files"] = count

    @staticmethod
    def _preprocess_flask_vars(text: str) -> str:
        """Replace Flask-specific Jinja2 constructs before brand rendering."""
        text = re.sub(
            r"\{\{\s*url_for\('static',\s*filename='([^']+)'\)\s*\}\}",
            r"static/\1", text,
        )
        text = re.sub(
            r"\{\{\s*url_for\('static',\s*filename=(\w+)\)\s*\}\}",
            lambda m: f"static/{m.group(1)}", text,
        )
        return text

    @staticmethod
    def _clean_jinja2(text: str) -> str:
        text = re.sub(r"\{\{.*?\}\}", "", text, flags=re.DOTALL)
        text = re.sub(r"\{%-?\s*.*?\s*-?%\}", "", text, flags=re.DOTALL)
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        return text


# ---------------------------------------------------------------------------
# Station: Nginx
# ---------------------------------------------------------------------------


class NginxStation(Station):
    def __init__(self) -> None:
        super().__init__("nginx")
        NGINX_AVAILABLE.mkdir(parents=True, exist_ok=True)
        NGINX_ENABLED.mkdir(parents=True, exist_ok=True)
        DEPLOY_BASE.mkdir(parents=True, exist_ok=True)

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        subdomain = context["subdomain"]
        site_path: Path = context["site_path"]
        domain = context["domain"]
        business_name = config.get("business_name", "")
        config_path = NGINX_AVAILABLE / subdomain
        enabled_path = NGINX_ENABLED / subdomain
        log_dir = Path("/var/log/nginx")
        log_dir.mkdir(parents=True, exist_ok=True)

        # robots.txt
        (site_path / "robots.txt").write_text("User-agent: *\nAllow: /\n")

        # 404 page
        (site_path / "404.html").write_text(
            f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Page Not Found — {business_name or domain}</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;text-align:center;padding-top:80px;color:#374151;background:#f9fafb;min-height:100vh;margin:0;}}
h1{{font-size:2rem;color:#111827;margin-bottom:16px;}}p{{font-size:1.1rem;color:#6b7280;margin-bottom:24px;}}
a{{color:#D42B2B;text-decoration:none;font-weight:600;}}a:hover{{text-decoration:underline;}}</style>
</head>
<body><h1>Oops! Page Not Found</h1><p>Sorry, the page you're looking for doesn't exist.</p>
<p><a href="/">Return to {business_name or 'Home'}</a></p></body></html>"""
        )

        # Nginx config
        config_path.write_text(
            f"""# Laval Digital — Client Site: {business_name or subdomain}
server {{
    listen 80; listen [::]:80;
    server_name {domain};
    root {site_path};
    index home.html index.html;
    access_log /var/log/nginx/{subdomain}.access.log;
    error_log /var/log/nginx/{subdomain}.error.log;
    error_page 404 /404.html;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    location / {{ try_files $uri $uri/ =404; }}
    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2|ttf|eot)$ {{
        expires 30d; add_header Cache-Control "public, immutable";
    }}
    location ~ /\\. {{ deny all; }}
}}""", encoding="utf-8",
        )
        if enabled_path.exists():
            enabled_path.unlink()
        enabled_path.symlink_to(config_path)

        # Test + reload nginx
        subprocess.run(["nginx", "-t"], check=True, capture_output=True, text=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True, capture_output=True, text=True)

        context["nginx_config_path"] = str(config_path)
        context["nginx_enabled_path"] = str(enabled_path)
        logger.info("Nginx deployed for %s", domain)

    def rollback(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        subdomain = context.get("subdomain")
        if subdomain:
            enabled_path = NGINX_ENABLED / subdomain
            config_path = NGINX_AVAILABLE / subdomain
            if enabled_path.exists():
                enabled_path.unlink()
            if config_path.exists():
                config_path.unlink()
            try:
                subprocess.run(["nginx", "-t"], check=True, capture_output=True, text=True)
                subprocess.run(["systemctl", "reload", "nginx"], check=True, capture_output=True, text=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Station: SSL
# ---------------------------------------------------------------------------


class SSLStation(Station):
    def __init__(self) -> None:
        super().__init__("ssl")

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        domain = context["domain"]
        if not shutil.which("certbot"):
            logger.warning("certbot not installed — SSL skipped")
            context["ssl_provisioned"] = False
            return
        try:
            result = subprocess.run(
                ["certbot", "--nginx", "-d", domain, "--non-interactive", "--agree-tos",
                 "-m", "lavaldigital@gmail.com"],
                capture_output=True, text=True, timeout=120,
            )
            ok = result.returncode == 0
            context["ssl_provisioned"] = ok
            if ok:
                logger.info("SSL provisioned for %s", domain)
        except Exception as e:
            logger.warning("SSL provisioning failed (non-fatal): %s", e)
            context["ssl_provisioned"] = False


# ---------------------------------------------------------------------------
# Station: Welcome email
# ---------------------------------------------------------------------------


class EmailStation(Station):
    def __init__(self) -> None:
        super().__init__("email")

    def run(self, config: Dict[str, Any], context: Dict[str, Any]) -> None:
        client_email = config.get("client_email", "")
        if not client_email:
            logger.warning("No client_email — welcome email skipped")
            context["email_sent"] = False
            return

        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USERNAME", "")
        smtp_pass = os.getenv("SMTP_PASSWORD", "")
        smtp_from = os.getenv("SMTP_FROM", "lavaldigital@gmail.com")

        if not smtp_user or not smtp_pass:
            logger.warning("SMTP not configured — welcome email skipped")
            context["email_sent"] = False
            return

        contact_name = config.get("contact_name", config.get("business_name", "there"))
        domain = context.get("domain", "")
        site_url = f"https://{domain}"
        admin_url = "https://lavaldigital.ca/admin"

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

Welcome to the Laval Digital family!

—
Laval Digital Team
"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Your AI-Powered Website is Live! 🚀"
        msg["From"] = smtp_from
        msg["To"] = client_email
        msg.attach(MIMEText(body, "plain", "utf-8"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info("Welcome email sent to %s", client_email)
            context["email_sent"] = True
        except Exception as e:
            logger.warning("Welcome email failed (non-fatal): %s", e)
            context["email_sent"] = False


# ---------------------------------------------------------------------------
# Pipeline definition — add / remove / reorder stations here
# ---------------------------------------------------------------------------

STATIONS: List[Station] = [
    ValidateStation(),
    SubdomainStation(),
    TenantStation(),
    CloneStation(),
    BrandStation(),
    NginxStation(),
    SSLStation(),
    EmailStation(),
]

_pipeline = Pipeline(STATIONS)


# ---------------------------------------------------------------------------
# Post-deployment hooks
# ---------------------------------------------------------------------------


def _fire_post_deploy_hooks(config: Dict[str, Any], context: Dict[str, Any]) -> None:
    """Publish deployment events to the EventBus."""
    try:
        from core.events import get_event_bus
        bus = get_event_bus()
        bus.publish("agent_executed", "client_factory", {
            "action": "deployed",
            "business_name": config.get("business_name", ""),
            "subdomain": context.get("subdomain", ""),
            "domain": context.get("domain", ""),
            "niche": config.get("niche", ""),
            "package": config.get("package", ""),
            "ssl": context.get("ssl_provisioned", False),
            "email": context.get("email_sent", False),
        })
        logger.info("Post-deploy hooks fired for %s", config.get("business_name", "?"))
    except Exception as e:
        logger.warning("Post-deploy hooks failed: %s", e)


# ---------------------------------------------------------------------------
# Legacy deploy() — synchronous, called by /api/clients/deploy
# ---------------------------------------------------------------------------


def deploy(config: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full deployment pipeline synchronously.

    This is the entry point called from ``/api/clients/deploy``.
    Returns the pipeline result dict.

    Args:
        config: Client configuration dict.

    Returns:
        Dict with ``success``, ``error``, ``subdomain``, ``site_url``, etc.
    """
    logger.info("=" * 60)
    logger.info("Starting deployment for: %s", config.get("business_name", "?"))
    logger.info("=" * 60)

    result = _pipeline.run(config)

    if result.get("success"):
        _fire_post_deploy_hooks(config, result)

    result.setdefault("subdomain", result.get("subdomain", ""))
    result.setdefault("site_url", result.get("site_url", ""))
    result.setdefault("admin_url", "https://lavaldigital.ca/admin")
    result.setdefault("tenant_id", result.get("subdomain"))

    return result


# ---------------------------------------------------------------------------
# Async deployment (background thread with status polling)
# ---------------------------------------------------------------------------


def deploy_async(config: Dict[str, Any]) -> str:
    """Start a deployment in a background thread.

    Returns a deployment ID that can be used to poll status
    via :func:`get_deploy_status`.
    """
    deploy_id = uuid.uuid4().hex[:12]
    status: Dict[str, Any] = {
        "id": deploy_id,
        "status": "running",
        "progress": [],
        "error": None,
        "result": None,
    }
    with _deploy_lock:
        _deploy_status[deploy_id] = status

    def _worker(cfg: Dict[str, Any], sid: str) -> None:
        try:
            result = deploy(cfg)
            with _deploy_lock:
                s = _deploy_status.get(sid)
                if s:
                    s["status"] = "completed" if result.get("success") else "failed"
                    s["result"] = result
                    s["error"] = result.get("error")
                    s["progress"] = result.get("_completed_stations", [])
        except Exception as e:
            with _deploy_lock:
                s = _deploy_status.get(sid)
                if s:
                    s["status"] = "failed"
                    s["error"] = str(e)

    thread = threading.Thread(target=_worker, args=(config, deploy_id), daemon=True)
    thread.start()
    return deploy_id


def get_deploy_status(deploy_id: str) -> Optional[Dict[str, Any]]:
    """Return the current status of an async deployment."""
    with _deploy_lock:
        status = _deploy_status.get(deploy_id)
        if status:
            return dict(status)
    return None


# ---------------------------------------------------------------------------
# Backward-compatible ClientFactory class
# ---------------------------------------------------------------------------


class ClientFactory:
    """Thin wrapper around the pipeline-based ``deploy()`` function.

    Kept for backward compatibility with ``app.py`` imports.
    """

    def deploy(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return deploy(config)

    def deploy_async(self, config: Dict[str, Any]) -> str:
        return deploy_async(config)

    @staticmethod
    def validate_config(config: dict) -> list:
        missing = []
        for field in REQUIRED_FIELDS:
            if field not in config or not config[field]:
                missing.append(field)
        return missing

    @staticmethod
    def generate_subdomain(business_name: str) -> str:
        return SubdomainStation.generate(business_name)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

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
        "payment_schedule": {"deposit": 3600, "installment_2": 4200, "installment_3": 4200},
    }

    print("=== Pipeline smoke test ===")
    result = _pipeline.run(sample_config)
    print(f"  success={result['success']}")
    if not result["success"]:
        print(f"  error={result['error']}")
    print(f"  stations completed: {result.get('_completed_stations', [])}")
