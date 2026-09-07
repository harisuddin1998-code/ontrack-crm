# src/web/suggestions.py
"""
Suggestions Routes - the users' channel to the Administrator.

Two views onto one set of records: everybody has their own dashboard of what
they have sent and what came of it, and whoever answers suggestions has a
wallboard of all of them - where each is coming from, who sent it, and when.

Raising a suggestion needs no role. Answering them needs `suggestion_manager`
or admin. Every check goes through SuggestionService so the two views cannot
disagree about who may see what.
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from src.web import suggestions_bp
from src.models.suggestion import Suggestion
from src.services.suggestion_service import SuggestionService
from src.utils.decorators import role_required
from src.utils.logging import get_logger

logger = get_logger(__name__)


def _sync_values(stats, suggestions=None):
    """Suggestion figures formatted for the live-sync loop.

    Same arrangement as the complaints and admin boards: one map, rendered
    into the page by Jinja and written back into it by the refresh, so a
    refreshed figure is produced by the code that produced the one on the
    page.

    The per-suggestion entries are what make an Administrator moving a
    suggestion to COMPLETED appear on the raiser's dashboard without them
    reloading anything - which is the whole point of telling them.
    """
    from src.utils.formatting import format_count

    values = {
        's_total': format_count(stats.get('total', 0)),
        's_new': format_count(stats.get('new', 0)),
        's_in_progress': format_count(stats.get('in_progress', 0)),
        's_completed': format_count(stats.get('completed', 0)),
        's_rejected': format_count(stats.get('rejected', 0)),
    }
    for s in (suggestions or []):
        values[f'sug_{s.id}_status'] = s.status_label()
        values[f'sug_{s.id}_replies'] = format_count(len(s.messages))
    return values


@suggestions_bp.route('/')
@login_required
def my_suggestions():
    """One user's own suggestions, and what has come of them."""
    service = SuggestionService()
    status = (request.args.get('status') or '').strip().upper()

    suggestions = service.for_user(current_user.id, status=status)
    stats = service.stats(user_id=current_user.id)

    return render_template('suggestions/my_dashboard.html',
                           suggestions=suggestions,
                           stats=stats,
                           sync=_sync_values(stats, suggestions),
                           status=status,
                           statuses=Suggestion.STATUS_LABELS)


@suggestions_bp.route('/api/sync')
@login_required
def api_my_sync():
    """Live values for one user's own suggestions dashboard."""
    service = SuggestionService()
    suggestions = service.for_user(current_user.id)
    stats = service.stats(user_id=current_user.id)
    return jsonify({'success': True, 'values': _sync_values(stats, suggestions)})


@suggestions_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    """Raise a suggestion. Open to every signed-in user, by design."""
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        area = (request.form.get('area') or '').strip()
        description = (request.form.get('description') or '').strip()

        if not title or not description:
            flash('A suggestion needs a title and a description.', 'warning')
            return render_template('suggestions/new.html', areas=Suggestion.AREAS,
                                   title_value=title, area_value=area,
                                   description_value=description)

        suggestion = SuggestionService().create(current_user, title, area, description)
        flash(f'Suggestion {suggestion.reference} sent to the Administrator. '
              'You can follow it here.', 'success')
        return redirect(url_for('suggestions.detail', suggestion_id=suggestion.id))

    return render_template('suggestions/new.html', areas=Suggestion.AREAS,
                           title_value='', area_value='', description_value='')


@suggestions_bp.route('/wallboard')
@login_required
@role_required('admin', 'suggestion_manager', 'executive')
def wallboard():
    """Every suggestion: where it came from, who sent it, and when.

    Open work first and oldest first within it, so the suggestion that has
    been waiting longest is the one at the top.
    """
    service = SuggestionService()

    status = (request.args.get('status') or '').strip().upper()
    area = (request.args.get('area') or '').strip()
    search = (request.args.get('search') or '').strip()

    suggestions = service.wallboard(status=status, area=area, search=search)
    stats = service.stats()

    return render_template('suggestions/wallboard.html',
                           suggestions=suggestions,
                           stats=stats,
                           sync=_sync_values(stats, suggestions),
                           status=status,
                           area=area,
                           search=search,
                           areas=Suggestion.AREAS,
                           statuses=Suggestion.STATUS_LABELS)


@suggestions_bp.route('/wallboard/api/sync')
@login_required
@role_required('admin', 'suggestion_manager', 'executive')
def api_wallboard_sync():
    """Live values for the suggestions wallboard."""
    service = SuggestionService()
    suggestions = service.wallboard()
    return jsonify({'success': True,
                    'values': _sync_values(service.stats(), suggestions)})


@suggestions_bp.route('/<int:suggestion_id>')
@login_required
def detail(suggestion_id):
    """One suggestion and its conversation, for either side of it."""
    service = SuggestionService()
    suggestion = service.get(suggestion_id)

    if not suggestion:
        flash('That suggestion no longer exists.', 'warning')
        return redirect(url_for('suggestions.my_suggestions'))

    if not service.can_view(suggestion, current_user):
        flash('You do not have permission to view this suggestion.', 'danger')
        return redirect(url_for('suggestions.my_suggestions'))

    # Someone who raised their own suggestion reads it as its author even if
    # they also happen to answer suggestions - the page they want is their
    # own, and replying to yourself as the Administrator would be nonsense.
    is_raiser = suggestion.raised_by == current_user.id
    can_manage = current_user.can_manage_suggestions() and not is_raiser

    return render_template('suggestions/detail.html',
                           suggestion=suggestion,
                           can_manage=can_manage,
                           statuses=Suggestion.STATUS_LABELS)


@suggestions_bp.route('/<int:suggestion_id>/reply', methods=['POST'])
@login_required
def reply(suggestion_id):
    """Add a message to a suggestion's thread, from either side."""
    service = SuggestionService()
    suggestion = service.get(suggestion_id)

    if not suggestion or not service.can_view(suggestion, current_user):
        flash('You do not have permission to reply to this suggestion.', 'danger')
        return redirect(url_for('suggestions.my_suggestions'))

    is_raiser = suggestion.raised_by == current_user.id
    body = request.form.get('body') or ''

    if not service.add_message(suggestion, current_user, body,
                               from_admin=current_user.can_manage_suggestions() and not is_raiser):
        flash('Write something before sending it.', 'warning')

    return redirect(url_for('suggestions.detail', suggestion_id=suggestion.id))


@suggestions_bp.route('/<int:suggestion_id>/status', methods=['POST'])
@login_required
@role_required('admin', 'suggestion_manager', 'executive')
def set_status(suggestion_id):
    """Move a suggestion to IN_PROGRESS, COMPLETED or REJECTED."""
    service = SuggestionService()
    suggestion = service.get(suggestion_id)

    if not suggestion:
        flash('That suggestion no longer exists.', 'warning')
        return redirect(url_for('suggestions.wallboard'))

    status = (request.form.get('status') or '').strip().upper()
    remarks = request.form.get('remarks') or ''

    try:
        service.set_status(suggestion, current_user, status, remarks)
        flash(f'{suggestion.reference} is now {suggestion.status_label()}. '
              f'{suggestion.raiser_name()} has been told.', 'success')
    except ValueError as e:
        flash(str(e), 'danger')

    return redirect(request.referrer or url_for('suggestions.wallboard'))
