"""Training hub blueprint — articles, search, and feedback."""
import json
import re
from flask import Blueprint, render_template, redirect, url_for, request, session
import logging

from core.api_helpers import api_success, api_error
from core.training_articles import ARTICLES as TRAINING_ARTICLES

logger = logging.getLogger(__name__)

training_bp = Blueprint("training", __name__, url_prefix="")

_TRAINING_BY_SLUG = {a["slug"]: a for a in TRAINING_ARTICLES}


@training_bp.route("/training")
def training_hub():
    """Serve the training hub landing page."""
    return render_template("blog/training_hub.html", articles=TRAINING_ARTICLES)


@training_bp.route("/training/<slug>")
def training_article(slug):
    """Serve an individual training article."""
    article = _TRAINING_BY_SLUG.get(slug)
    if not article:
        return redirect(url_for("training.training_hub"))

    content_html = article.get("content_html", "")
    content_html = re.sub(r'<script[^>]*>.*?</script>', '', content_html, flags=re.DOTALL)
    article = {**article, "content_html": content_html}

    related = [
        a for a in TRAINING_ARTICLES
        if a["slug"] != slug and a["category"] == article["category"]
    ][:3]

    return render_template(
        "blog/training_article.html",
        article=article,
        related=related,
    )


@training_bp.route("/api/training/articles")
def api_training_articles():
    """Return the list of training articles (for search/filter)."""
    return api_success(TRAINING_ARTICLES)


@training_bp.route("/api/training/feedback", methods=["POST"])
def api_training_feedback():
    """Log training article feedback."""
    if not session.get("admin_logged_in") and not session.get("_user_id"):
        return api_error("Unauthorized", 401)
    data = request.json
    slug = data.get("slug", "")
    helpful = data.get("helpful")
    logger.info("Training feedback: slug=%s helpful=%s", slug, helpful)
    return api_success()
