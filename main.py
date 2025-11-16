import eventlet
eventlet.monkey_patch()

from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'remote-desktop-secret-key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

sessions = {}
hosts = {}
viewers = {}

@app.route('/')
def index():
    return {
        'status': 'Remote Desktop Server Running',
        'active_sessions': len(sessions),
        'hosts': len(hosts),
        'viewers': len(viewers)
    }

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    print(f'Client disconnected: {sid}')
    
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
    session_id = data.get('session_id', sid)
    
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
    print(f'Host registered: {sid} -> Session: {session_id}')
    emit('host_registered', {
        'session_id': session_id,
        'message': 'Host registered successfully'
    })

@socketio.on('register_viewer')
def handle_register_viewer(data):
    sid = request.sid
    session_id = data.get('session_id')
    
    if not session_id or session_id not in sessions:
        emit('error', {'message': 'Invalid session ID'})
        return
    
    viewers[sid] = session_id
    sessions[session_id]['viewer'] = sid
    
    join_room(session_id)
    print(f'Viewer registered: {sid} -> Session: {session_id}')
    
    host_sid = sessions[session_id]['host']
    emit('viewer_registered', {
        'session_id': session_id,
        'message': 'Viewer connected successfully'
    })
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
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
