"""Affiliate blueprint — signup, login, dashboard, API, admin routes."""
import os
import secrets
import logging
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for,
    session, request, flash,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from core import database
from core.api_helpers import api_success, api_error
from core.auth import (
    User, find_user_by_email, add_user_to_tenant,
    validate_password, admin_required, _check_rate_limit, _record_attempt,
)


logger = logging.getLogger(__name__)

affiliate_bp = Blueprint("affiliate", __name__, url_prefix="")

# ---------------------------------------------------------------------------
# Public page routes
# ---------------------------------------------------------------------------

@affiliate_bp.route("/affiliate")
def affiliate_signup():
    """Serve the affiliate program signup page."""
    has_ref = "affiliate_ref" in session
    return render_template("affiliate.html", has_ref=has_ref)


@affiliate_bp.route("/fr/affiliate")
def affiliate_signup_fr():
    """Serve the French affiliate program signup page."""
    has_ref = "affiliate_ref" in session
    return render_template("affiliate_fr.html", has_ref=has_ref)


# ---------------------------------------------------------------------------
# Affiliate auth routes
# ---------------------------------------------------------------------------

@affiliate_bp.route("/affiliate/login", methods=["GET", "POST"])
def affiliate_login():
    """Serve affiliate login page and authenticate."""
    if current_user.is_authenticated and current_user.role == "affiliate":
        return redirect(url_for("affiliate.affiliate_dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not _check_rate_limit("affiliate"):
            flash("Too many login attempts. Try again later.", "error")
            return render_template("affiliate/login.html")

        user_row = find_user_by_email(email)
        if not user_row or user_row["role"] != "affiliate":
            _record_attempt(False, "affiliate")
            flash("Invalid email or password.", "error")
            return render_template("affiliate/login.html")

        temp_user = User(
            row_id=user_row["id"], email=user_row["email"],
            password_hash=user_row["password_hash"], role=user_row["role"],
            display_name=user_row["display_name"],
        )
        if not temp_user.check_password(password):
            _record_attempt(False, "affiliate")
            flash("Invalid email or password.", "error")
            return render_template("affiliate/login.html")

        login_user(temp_user)
        _record_attempt(True, "affiliate")
        session["tenant_id"] = str(user_row["id"])
        session["user_role"] = "affiliate"
        session["last_active"] = datetime.now().isoformat()

        try:
            conn = database._get_conn()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_row["id"]),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Silent exception in %s: %s", __name__, e)

        return redirect(url_for("affiliate.affiliate_dashboard"))

    return render_template("affiliate/login.html")


@affiliate_bp.route("/affiliate/logout")
def affiliate_logout():
    """Log out affiliate and redirect to login."""
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("affiliate.affiliate_login"))


@affiliate_bp.route("/affiliate/dashboard")
@login_required
def affiliate_dashboard():
    """Serve the affiliate referral dashboard."""
    from core.app_state import get_affiliate_manager
    affiliate_manager = get_affiliate_manager()
    tenant_id = current_user.id

    aff = affiliate_manager.get_affiliate(tenant_id)
    profile = aff or {}

    referrals = affiliate_manager.get_leads(tenant_id)
    stats = {"total_clicks": 0, "total_leads": 0, "total_clients": 0, "total_commissions": 0}
    for r in referrals:
        if r.get("status") == "client":
            stats["total_clients"] += 1
            stats["total_commissions"] += r.get("commission") or 0
        else:
            stats["total_leads"] += 1

    commissions = affiliate_manager.get_commissions(tenant_id)
    payouts = affiliate_manager.get_payouts(tenant_id)

    referral_link = f"https://lavaldigital.ca/?ref={tenant_id}"

    return render_template(
        "affiliate/dashboard.html",
        stats=stats,
        referrals=referrals,
        payouts=payouts,
        commissions=commissions,
        profile=profile,
        referral_link=referral_link,
    )


# ---------------------------------------------------------------------------
# API: affiliate
# ---------------------------------------------------------------------------

@affiliate_bp.route("/api/affiliate/status")
def affiliate_status():
    """Return current affiliate status for the visitor."""
    from core.app_state import get_affiliate_manager
    affiliate_manager = get_affiliate_manager()
    ref_code = session.get("affiliate_ref")
    if ref_code and affiliate_manager.is_valid_code(ref_code):
        aff = affiliate_manager.get_affiliate(ref_code)
        if aff:
            return api_success({
                "active": True,
                "code": ref_code,
                "discount": 500,
                "affiliate_name": aff.get("name", "Partner"),
            })
    return api_success({"active": False, "discount": 0})


@affiliate_bp.route("/api/affiliate/signup", methods=["POST"])
def affiliate_signup_api():
    """Register a new affiliate and return their referral code."""
    from app import affiliate_manager
    data = request.json
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not name or not email:
        return api_error("Name and email are required", 400)

    try:
        aff = affiliate_manager.create_affiliate(name, email, phone)
        code = aff["code"]

        password = secrets.token_urlsafe(12) + "A1!"
        try:
            result = add_user_to_tenant(email, password, "affiliate", name)
            uid = result.get("user_id")
            if uid:
                conn = database._get_conn()
                conn.execute("UPDATE affiliates SET user_id = ? WHERE code = ?", (uid, code))
                conn.commit()
            logger.info("Affiliate user created: %s (id=%s, code=%s)", email, uid, code)
        except Exception as e:
            logger.error("Failed to create affiliate user for %s: %s", email, e)
            return api_error("Account creation failed. Please try again later.", 500)

        return api_success({
            "code": code,
            "referral_link": f"https://lavaldigital.ca/?ref={code}",
            "message": f"Account created. Your password is: {password}. Please save it.",
            "password": password,
        }, status_code=201)
    except Exception as e:
        logger.error("Affiliate signup failed: %s", e, exc_info=True)
        return api_error("Signup failed. Please try again.", 500)


# ---------------------------------------------------------------------------
# API: affiliate payouts
# ---------------------------------------------------------------------------

@affiliate_bp.route("/api/affiliate/commissions", methods=["GET"])
@login_required
def api_affiliate_commissions():
    """Return the current affiliate's commission history."""
    from core.app_state import get_affiliate_manager
    affiliate_manager = get_affiliate_manager()
    tenant_id = current_user.tenant_id
    commissions = affiliate_manager.get_commissions(tenant_id)
    total_pending = sum(c["amount"] for c in commissions if c["status"] == "pending")
    total_paid = sum(c["amount"] for c in commissions if c["status"] == "paid")
    return api_success({
        "commissions": commissions,
        "total_pending": total_pending,
        "total_paid": total_paid,
    })


@affiliate_bp.route("/api/affiliate/payouts", methods=["GET"])
@login_required
def api_affiliate_payouts():
    """Return the current affiliate's payout history."""
    from core.app_state import get_affiliate_manager
    affiliate_manager = get_affiliate_manager()
    tenant_id = current_user.tenant_id
    return api_success({"payouts": affiliate_manager.get_payouts(tenant_id)})


@affiliate_bp.route("/api/affiliate/payouts", methods=["POST"])
@login_required
def api_request_payout():
    """Request a payout for the current affiliate's pending commissions."""
    from core.app_state import get_affiliate_manager
    affiliate_manager = get_affiliate_manager()
    tenant_id = current_user.tenant_id
    commissions = affiliate_manager.get_commissions(tenant_id)
    total_pending = sum(c["amount"] for c in commissions if c["status"] == "pending")
    if total_pending < 50:
        return api_error("Minimum payout is $50. You have $" + str(round(total_pending, 2)), 400)
    payout_id = affiliate_manager.create_payout(tenant_id, total_pending)
    if payout_id:
        return api_success({"payout_id": payout_id, "amount": total_pending})
    return api_error("Failed to create payout", 500)


# ---------------------------------------------------------------------------
# API: admin affiliates
# ---------------------------------------------------------------------------

@affiliate_bp.route("/api/admin/affiliates", methods=["GET"])
def api_admin_affiliates():
    auth_check = admin_required()
    if auth_check:
        return auth_check
    from core.app_state import get_affiliate_manager
    affiliate_manager = get_affiliate_manager()
    affiliates = affiliate_manager.get_all_affiliates()
    commissions = affiliate_manager.get_all_commissions(limit=200)
    payouts = affiliate_manager.get_payouts(limit=200)
    return api_success({
        "affiliates": affiliates,
        "recent_commissions": commissions,
        "recent_payouts": payouts,
    })


@affiliate_bp.route("/api/admin/affiliates/<code>/payout", methods=["POST"])
def api_admin_process_payout(code):
    auth_check = admin_required()
    if auth_check:
        return auth_check
    from core.app_state import get_affiliate_manager
    affiliate_manager = get_affiliate_manager()
    data = request.json
    payout_id = data.get("payout_id", "")
    if not payout_id:
        return api_error("payout_id required", 400)
    success = affiliate_manager.process_payout(payout_id)
    if success:
        return api_success(message="Payout processed")
    return api_error("Payout not found or already processed", 404)
