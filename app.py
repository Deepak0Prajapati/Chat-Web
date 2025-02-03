from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from translate import Translator
from textblob import TextBlob
import threading
import socket
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet')

# Store user details (name and language preference)
users = {}

class Server(threading.Thread):
    def __init__(self, host, port):
        super().__init__()
        self.connections = []
        self.host = host
        self.port = port

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(1)
        print("Listening at", sock.getsockname())

        while True:
            sc, sockname = sock.accept()
            print(f"Accepted new connection from {sc.getpeername()} to {sc.getsockname()}")

            server_socket = ServerSocket(sc, sockname, self)
            server_socket.start()
            self.connections.append(server_socket)
            print("Ready to receive messages from", sc.getpeername())

    def broadcast(self, message, source):
        for connection in self.connections:
            if connection.sockname != source:
                connection.send(message)

    def remove_connection(self, connection):
        self.connections.remove(connection)

class ServerSocket(threading.Thread):
    def __init__(self, sc, sockname, server):
        super().__init__()
        self.sc = sc
        self.sockname = sockname
        self.server = server

    def run(self):
        while True:
            message = self.sc.recv(1024).decode('utf-8')
            if message:
                print(f"{self.sockname} says {message}")
                self.server.broadcast(message, self.sockname)
            else:
                print(f"{self.sockname} has closed the connection")
                self.sc.close()
                self.server.remove_connection(self)
                return

    def send(self, message):
        self.sc.sendall(message.encode('utf-8'))

# Start the server in a separate thread
server = Server('127.0.0.1', 1060)
server.start()

# WebSocket events
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')
    if request.sid in users:
        del users[request.sid]

@socketio.on('join')
def handle_join(data):
    name = data['name']
    preferred_language = data['language']
    users[request.sid] = {'name': name, 'language': preferred_language}
    emit('broadcast_message', {'name': 'Server', 'message': f'{name} has joined the chat.'}, broadcast=True)

@socketio.on('message')
def handle_message(data):
    message = data['message']
    user = users.get(request.sid)
    if not user:
        return

    name = user['name']
    sender_language = user['language']

    # Send the original message back to the sender (without sentiment)
    emit('broadcast_message', {
        'name': name,
        'message': message,
        'is_own_message': True  # Mark as the sender's own message
    }, room=request.sid)

    # Broadcast the message to other users (with translation and sentiment)
    for sid, recipient in users.items():
        if sid != request.sid:  # Don't send to the sender
            translator = Translator(from_lang=sender_language, to_lang=recipient['language'])
            try:
                translated_message = translator.translate(message) if sender_language != recipient['language'] else message
                emit('broadcast_message', {
                    'name': name,
                    'message': translated_message,
                    'is_own_message': False  # Mark as another user's message
                }, room=sid)

                # Sentiment analysis for the receiver's message
                sentiment = TextBlob(message).sentiment
                sentiment_text = f"Sentiment: Polarity={sentiment.polarity}, Subjectivity={sentiment.subjectivity}"
                emit('sentiment', {'sentiment': sentiment_text}, room=sid)
            except Exception as e:
                print(f"Translation error: {e}")
                emit('broadcast_message', {
                    'name': name,
                    'message': message,
                    'is_own_message': False  # Mark as another user's message
                }, room=sid)

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/join', methods=['POST'])
def join_chat():
    name = request.form['name']
    preferred_language = request.form['language']
    return jsonify({'status': 'success', 'name': name, 'language': preferred_language})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)