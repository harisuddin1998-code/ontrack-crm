# src/api/v1/auth.py
"""
Authentication API Endpoints
"""
from typing import cast

from flask import request, jsonify
from flask_login import login_user, logout_user, login_required, current_user

from src.api import api_v1_bp
from src.models.user import User
from src.services.auth_service import ACTION_LOGOUT, AuthService
from src.schemas.auth_schemas import LoginRequest, LoginResponse, UserResponse
from src.utils.logging import get_logger

logger = get_logger(__name__)
auth_service = AuthService()


@api_v1_bp.route('/auth/login', methods=['POST'])
def login():
    """
    User login
    ---
    tags:
      - Authentication
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required:
            - username
            - password
          properties:
            username:
              type: string
              description: Username
            password:
              type: string
              description: Password
    responses:
      200:
        description: Login successful
        schema:
          type: object
          properties:
            success:
              type: boolean
            user:
              type: object
              properties:
                id:
                  type: integer
                username:
                  type: string
                email:
                  type: string
                name:
                  type: string
                role:
                  type: string
      401:
        description: Invalid credentials
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    user = auth_service.authenticate(
        username=username,
        password=password,
        ip_address=request.remote_addr
    )
    
    if user:
        login_user(user, remember=data.get('remember_me', False))
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'name': user.name,
                'role': user.role,
                'role_display': user.get_role_display()
            }
        }), 200
    
    return jsonify({'error': 'Invalid username or password'}), 401


@api_v1_bp.route('/auth/logout', methods=['POST'])
@login_required
def logout():
    """
    User logout
    """
    # Before the session is torn down: afterwards `current_user` is anonymous
    # and there is nobody left to record the sign-out against.
    auth_service.record_session_event(current_user, ACTION_LOGOUT)

    logout_user()
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200


@api_v1_bp.route('/auth/me', methods=['GET'])
@login_required
def get_current_user():
    """
    Get current user information
    """
    if current_user:
        return jsonify({
            'id': current_user.id,
            'username': current_user.username,
            'email': current_user.email,
            'name': current_user.name,
            'role': current_user.role,
            'role_display': current_user.get_role_display(),
            'is_active': current_user.is_active,
            'last_login': current_user.last_login.isoformat() if current_user.last_login else None,
            'permissions': auth_service.get_user_permissions(cast(User, current_user))
        }), 200
    
    return jsonify({'error': 'Not authenticated'}), 401


@api_v1_bp.route('/auth/change-password', methods=['POST'])
@login_required
def change_password():
    """
    Change user password
    """
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'Missing request body'}), 400
    
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    if not old_password or not new_password:
        return jsonify({'error': 'Old and new password required'}), 400
    
    success, message = auth_service.change_password(
        user_id=current_user.id,
        old_password=old_password,
        new_password=new_password
    )
    
    if success:
        return jsonify({'success': True, 'message': message}), 200
    
    return jsonify({'error': message}), 400


@api_v1_bp.route('/auth/reset-password', methods=['POST'])
def reset_password_request():
    """
    Request password reset
    """
    data = request.get_json()
    email = data.get('email') if data else None
    
    if not email:
        return jsonify({'error': 'Email required'}), 400
    
    success, message = auth_service.reset_password(email)
    
    if success:
        return jsonify({'success': True, 'message': message}), 200
    
    return jsonify({'error': message}), 400 
