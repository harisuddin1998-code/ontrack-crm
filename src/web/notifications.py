# src/web/notifications.py
"""
Notification endpoints backing the desktop notifications in base.html.

Everything here is scoped to `current_user` and nothing takes a user id from
the client - a notification is personal, and "show me notification 41" must
never be able to read someone else's.
"""
from datetime import datetime

from flask import jsonify, request
from flask_login import login_required, current_user

from src.extensions import db
from src.models.notification import UserNotification
from src.utils.logging import get_logger
from src.web import notifications_bp

logger = get_logger(__name__)

# How many to hand the browser at once. The bell shows a count, not a
# transcript - anything older than this is history, not a notification.
FEED_LIMIT = 20


def _my_notifications(unread_only: bool = True):
    query = UserNotification.query.filter(UserNotification.user_id == current_user.id)
    if unread_only:
        query = query.filter(UserNotification.is_read.is_(False))
    return query.order_by(UserNotification.created_at.desc()).limit(FEED_LIMIT).all()


@notifications_bp.route('/feed')
@login_required
def feed():
    """Unread notifications for the signed-in user.

    `undelivered` marks the ones the browser has not yet raised as a desktop
    notification, so a reload doesn't pop the same toast a second time.
    """
    notes = _my_notifications(unread_only=True)
    undelivered = [n for n in notes if n.delivered_at is None]

    return jsonify({
        'success': True,
        'unread_count': len(notes),
        'notifications': [n.to_dict() for n in notes],
        'undelivered': [n.to_dict() for n in undelivered],
    })


@notifications_bp.route('/delivered', methods=['POST'])
@login_required
def mark_delivered():
    """Record that the browser has shown these as desktop notifications."""
    ids = (request.get_json(silent=True) or {}).get('ids') or []
    if not ids:
        return jsonify({'success': True, 'updated': 0})

    rows = UserNotification.query.filter(
        UserNotification.user_id == current_user.id,
        UserNotification.id.in_(ids)).all()
    for row in rows:
        row.delivered_at = datetime.now()
    db.session.commit()
    return jsonify({'success': True, 'updated': len(rows)})


@notifications_bp.route('/read', methods=['POST'])
@login_required
def mark_read():
    """Mark notifications read. With no ids, marks everything read."""
    ids = (request.get_json(silent=True) or {}).get('ids')

    query = UserNotification.query.filter(
        UserNotification.user_id == current_user.id,
        UserNotification.is_read.is_(False))
    if ids:
        query = query.filter(UserNotification.id.in_(ids))

    rows = query.all()
    now = datetime.now()
    for row in rows:
        row.is_read = True
        row.read_at = now
    db.session.commit()
    return jsonify({'success': True, 'updated': len(rows)})
