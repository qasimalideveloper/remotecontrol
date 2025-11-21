import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
import time
import uuid
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SERVER] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)

app = Flask(__name__)
# Use environment variable for secret key in production
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'remote-desktop-secret-key-change-in-production')
CORS(app)

# Get configuration from environment variables (for Render)
PORT = int(os.getenv('PORT', 5000))
HOST = os.getenv('HOST', '0.0.0.0')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

socketio = SocketIO(
    app,
    cors_allowed_origins="*",  # In production, specify allowed origins
    async_mode='eventlet',
    ping_interval=10,
    ping_timeout=30,
    max_http_buffer_size=50_000_000,  # 50MB for large frames
    logger=DEBUG,
    engineio_logger=DEBUG,
    allow_upgrades=True,
    transports=['websocket', 'polling']  # Support both for better compatibility
)

sessions = {}
hosts = {}
viewers = {}


def generate_session_id():
    return uuid.uuid4().hex


def find_available_session():
    for session_id, data in sessions.items():
        if data['host'] and data['viewer'] is None:
            return session_id
    return None

@app.route('/')
def index():
    """Health check endpoint"""
    return jsonify({
        'status': 'Remote Desktop Server Running',
        'active_sessions': len(sessions),
        'hosts': len(hosts),
        'viewers': len(viewers),
        'version': '1.0.0'
    })

@app.route('/health')
def health():
    """Health check for Render"""
    return jsonify({'status': 'healthy'}), 200

@socketio.on('connect')
def handle_connect():
    logging.info(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    logging.info(f'Client disconnected: {sid}')
    
    if sid in hosts:
        session_id = hosts[sid]
        if session_id in sessions:
            viewer_sid = sessions[session_id].get('viewer')
            if viewer_sid:
                emit('host_disconnected', room=viewer_sid)
            del sessions[session_id]
        del hosts[sid]
    
    if sid in viewers:
        session_id = viewers[sid]
        if session_id in sessions:
            host_sid = sessions[session_id].get('host')
            if host_sid:
                emit('viewer_disconnected', room=host_sid)
            sessions[session_id]['viewer'] = None
        del viewers[sid]

@socketio.on('register_host')
def handle_register_host(data):
    sid = request.sid
    session_id = data.get('session_id') or generate_session_id()
    
    hosts[sid] = session_id
    
    if session_id not in sessions:
        sessions[session_id] = {
            'host': sid,
            'viewer': None,
            'created_at': time.time()
        }
    else:
        sessions[session_id]['host'] = sid
    
    join_room(session_id)
    logging.info(f'Host registered: {sid} -> Session: {session_id}')
    emit('host_registered', {
        'session_id': session_id,
        'message': 'Host registered successfully'
    })

@socketio.on('register_viewer')
def handle_register_viewer(data):
    sid = request.sid
    requested_session = data.get('session_id')
    session_id = None
    
    if requested_session and requested_session in sessions:
        if sessions[requested_session]['viewer'] is None and sessions[requested_session]['host']:
            session_id = requested_session
    
    if session_id is None:
        session_id = find_available_session()
    
    if session_id is None:
        emit('error', {'message': 'No available hosts to connect to'})
        return
    
    viewers[sid] = session_id
    sessions[session_id]['viewer'] = sid
    
    join_room(session_id)
    logging.info(f'Viewer registered: {sid} -> Session: {session_id}')
    
    host_sid = sessions[session_id]['host']
    emit('viewer_registered', {
        'session_id': session_id,
        'message': 'Viewer connected successfully'
    })
    if host_sid:
        emit('viewer_connected', room=host_sid)

@socketio.on('screen_frame')
def handle_screen_frame(data):
    sid = request.sid
    
    if sid not in hosts:
        return
    
    session_id = hosts[sid]
    if session_id not in sessions:
        return
    
    viewer_sid = sessions[session_id].get('viewer')
    if viewer_sid:
        emit('screen_frame', data, room=viewer_sid)

@socketio.on('control_event')
def handle_control_event(data):
    sid = request.sid
    
    if sid not in viewers:
        return
    
    session_id = viewers[sid]
    if session_id not in sessions:
        return
    
    host_sid = sessions[session_id].get('host')
    if host_sid:
        emit('control_event', data, room=host_sid)

@socketio.on('get_sessions')
def handle_get_sessions():
    active_sessions = []
    for session_id, session_data in sessions.items():
        active_sessions.append({
            'session_id': session_id,
            'has_host': session_data['host'] is not None,
            'has_viewer': session_data['viewer'] is not None
        })
    emit('sessions_list', {'sessions': active_sessions})

if __name__ == '__main__':
    logging.info(f'Starting server on {HOST}:{PORT} (debug={DEBUG})')
    socketio.run(app, host=HOST, port=PORT, debug=DEBUG, use_reloader=False)
