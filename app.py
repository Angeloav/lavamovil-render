import os
IS_WINDOWS = os.name == "nt"

# Usa eventlet solo cuando NO sea Windows (ej. Render)
if not IS_WINDOWS:
    import eventlet
    eventlet.monkey_patch()
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from flask_session import Session
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "lavamovil.db")}'
app.config['UPLOAD_FOLDER'] = 'static/bauches'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = os.path.join(os.getcwd(), 'flask_session')


db = SQLAlchemy(app)
Session(app)

ASYNC_MODE = "eventlet" if not IS_WINDOWS else "threading"
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*", logger=True, engineio_logger=True)
                    logger=True, engineio_logger=True)

# Modelos
class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rol = db.Column(db.String(50))
    nombre = db.Column(db.String(50))
    apellido = db.Column(db.String(50))
    telefono = db.Column(db.String(20))
    estado = db.Column(db.String(20), default='inactivo')
    latitud = db.Column(db.Float)
    longitud = db.Column(db.Float)
    suscrito = db.Column(db.Boolean, default=False)
    fecha_aprobacion = db.Column(db.DateTime, nullable=True)
    fecha_expiracion = db.Column(db.DateTime, nullable=True)
    bauche = db.Column(db.String(200))
    id_personal = db.Column(db.String(50))
    descripcion = db.Column(db.String(200))

class Mensaje(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    de_id = db.Column(db.Integer)
    para_id = db.Column(db.Integer)
    texto = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
class Solicitud(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer)
    estado = db.Column(db.String(50), default='pendiente')
    latitud = db.Column(db.Float)  
    longitud = db.Column(db.Float)
    lavador_id = db.Column(db.Integer)
    calificacion = db.Column(db.String(50))
    comentario = db.Column(db.String(200))

    tiene_mensajes_nuevos = db.Column(db.Boolean, default=False)

class Calificacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer)
    lavador_id = db.Column(db.Integer)
    calificacion = db.Column(db.String(50))
    comentario = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Rutas principales
@app.route('/')
def index():
    return render_template('seleccion_rol.html')

@app.route('/seleccionar_rol', methods=['POST'])
def seleccionar_rol():
    rol = request.form['rol']
    if rol == 'cliente':
        return redirect(url_for('registro_cliente'))
    elif rol == 'lavador':
        return redirect(url_for('registro_lavador'))

@app.route('/registro_cliente', methods=['GET', 'POST'])
def registro_cliente():
    if request.method == 'POST':
        nombre = request.form['nombre']
        apellido = request.form['apellido']
        telefono = request.form['telefono']

        cliente = Usuario(rol='cliente', nombre=nombre, apellido=apellido, telefono=telefono, suscrito=True)
        db.session.add(cliente)
        db.session.commit()
        
        session['usuario_id'] = cliente.id  # 🔑 Necesaria para la mayoría de rutas
        session['cliente_id'] = cliente.id  # 🔑 Necesaria para cliente_dashboard

        return redirect(url_for('cliente_dashboard'))

    return render_template('registro_cliente.html')

@app.route('/cliente_dashboard')
def cliente_dashboard():
    cliente_id = session.get('cliente_id')
    if not cliente_id:
        print("❌ cliente_id no está en sesión")
        return redirect(url_for('registro_cliente'))

    cliente = db.session.get(Usuario, cliente_id)
    if not cliente:
        print("❌ Cliente no encontrado en la base de datos")
        return redirect(url_for('registro_cliente'))

    solicitud_activa = Solicitud.query.filter_by(cliente_id=cliente.id, estado='aceptado').first()
    if solicitud_activa:
        print(f"✅ Solicitud encontrada: estado = {solicitud_activa.estado}")
    else:
        print("ℹ️ No hay solicitud activa para este cliente")

    return render_template("cliente_dashboard.html", cliente=cliente, solicitud_activa=solicitud_activa)

@app.route('/registro_lavador', methods=['GET', 'POST'])
def registro_lavador():
    if request.method == 'POST':
        nombre = request.form['nombre']
        apellido = request.form['apellido']
        telefono = request.form['telefono']

        lavador = Usuario(rol='lavador', nombre=nombre, apellido=apellido, telefono=telefono)
        db.session.add(lavador)
        db.session.commit()

        session['lavador_id'] = lavador.id  # Guarda lo correcto

        return redirect(url_for('lavador_formulario'))

    return render_template('registro_lavador.html')

@app.route('/lavador_formulario', methods=['GET', 'POST'])
def lavador_formulario():
    if 'lavador_id' not in session:
        return redirect(url_for('registro_lavador'))

    lavador = Usuario.query.get(session['lavador_id'])
    if not lavador:
        return 'Lavador no encontrado. Por favor regístrate de nuevo.'

    if lavador.nombre and lavador.apellido and lavador.id_personal:
        return redirect(url_for('lavador_pago'))

    if request.method == 'POST':
        lavador.nombre = request.form['nombre']
        lavador.apellido = request.form['apellido']
        lavador.id_personal = request.form['id_personal']
        lavador.telefono = request.form['telefono']
        lavador.descripcion = request.form['descripcion']
        lavador.estado = 'inactivo'
        db.session.commit()
        return redirect(url_for('lavador_pago'))

    return render_template('lavador_formulario.html', lavador=lavador)  # 👈 ESTA LÍNEA ES CLAVE

@app.route('/lavador_pago')
def lavador_pago():
    if 'lavador_id' not in session:
        return redirect(url_for('registro_lavador'))

    lavador = Usuario.query.get(session['lavador_id'])
    return render_template('lavador_pago.html', lavador=lavador)

@app.route('/subir_bauche', methods=['POST'])
def subir_bauche():
    if 'lavador_id' not in session:
        return redirect(url_for('registro_lavador'))

    lavador_id = session.get('lavador_id')
    lavador = Usuario.query.get(lavador_id)

    if not lavador:
        return 'Lavador no encontrado. Por favor regístrate de nuevo.'

    if 'bauche' not in request.files:
        return 'No se envió ningún archivo.'

    file = request.files['bauche']
    if file.filename == '':
        return 'No se seleccionó ningún archivo.'

    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        lavador.bauche = filename
        lavador.estado = 'inactivo'
        db.session.commit()

        session['lavador_id'] = lavador.id  # ✅ mantenemos la sesión correcta

        print(f"✅ Bauche subido por {lavador.nombre} (ID: {lavador.id})")

        return render_template('lavador_pago.html', mensaje='Comprobante subido correctamente. Espera aprobación del administrador.', lavador=lavador)

    return 'Archivo inválido o no se pudo procesar.'

@app.route('/aprobar_bauche', methods=['POST'])
def aprobar_bauche():
    lavador_id = request.form.get('lavador_id')
    lavador = Usuario.query.get(lavador_id)

    if lavador:
        lavador.estado = 'activo'
        lavador.suscrito = True
        db.session.commit()

        print(f"✅ Lavador aprobado: {lavador.nombre} (ID: {lavador.id})")

        # ✅ Emitir evento al lavador para abrir su dashboard
        socketio.emit('bauche_aprobado', {
            'lavador_id': lavador.id,
            'mensaje': '¡Tu comprobante ha sido aprobado! Puedes comenzar a trabajar.'
        })

        return redirect(url_for('admin_bauches'))

    return 'Lavador no encontrado', 404

@app.route('/lavador_dashboard')
def lavador_dashboard():
    lavador_id = session.get('lavador_id')
    if not lavador_id:
        return redirect(url_for('registro_lavador'))

    lavador = db.session.get(Usuario, lavador_id)
    if not lavador:
        return redirect(url_for('registro_lavador'))

    solicitud_activa = Solicitud.query.filter_by(lavador_id=lavador.id, estado='aceptado').first()
    cliente = Usuario.query.get(solicitud_activa.cliente_id) if solicitud_activa else None

    return render_template("lavador_dashboard.html", lavador=lavador, cliente=cliente, solicitud_activa=solicitud_activa)

@app.route('/rechazar_bauche', methods=['POST'])
def rechazar_bauche():
    lavador_id = request.form['lavador_id']
    lavador = Usuario.query.get(lavador_id)
    if lavador:
        lavador.suscrito = False
        db.session.commit()
        socketio.emit('bauche_rechazado', {'lavador_id': lavador.id})
        return 'Bauche rechazado.'
    return 'Lavador no encontrado.'

@app.route('/admin_bauches')
def admin_bauches():
    if 'admin' not in session:
        print("❌ Acceso denegado. No hay sesión de administrador.")
        return redirect(url_for('admin_login'))

    bauches_pendientes = Usuario.query.filter(
        Usuario.bauche != None,
        Usuario.rol == 'lavador',
        Usuario.estado == 'inactivo'
    ).all()

    return render_template('admin_bauches.html', bauches=bauches_pendientes)

@app.route('/admin_dashboard')
def admin_dashboard():
    admin = Usuario.query.filter_by(rol='admin').first()
    if admin:
        session['usuario_id'] = admin.id  # ✅ Guarda el ID del admin en la sesión

    solicitudes = Solicitud.query.all()
    for s in solicitudes:
        cliente = Usuario.query.get(s.cliente_id)
        lavador = Usuario.query.get(s.lavador_id)
        s.cliente_nombre = cliente.nombre if cliente else '---'
        s.cliente_apellido = cliente.apellido if cliente else ''
        s.lavador_nombre = lavador.nombre if lavador else '---'
        s.lavador_apellido = lavador.apellido if lavador else ''
        
    return render_template('admin_dashboard.html', solicitudes=solicitudes)

# 🔧 INICIO PARCHE /datos_lavador
@app.route('/datos_lavador', methods=['GET'])
def datos_lavador():
    try:
        lavador_id = session.get('lavador_id') or session.get('usuario_id')
        if not lavador_id:
            return jsonify({'ok': False, 'error': 'sin_sesion'}), 401
        try:
            lavador_id = int(lavador_id)
        except Exception:
            return jsonify({'ok': False, 'error': 'id_invalido'}), 400
        lavador = Usuario.query.get(lavador_id)
        if not lavador:
            return jsonify({'ok': False, 'error': 'no_encontrado'}), 404
        return jsonify({'ok': True, 'lavador': {
            'id': lavador.id,
            'nombre': getattr(lavador, 'nombre', ''),
            'apellido': getattr(lavador, 'apellido', ''),
            'telefono': getattr(lavador, 'telefono', '')
        }}), 200
    except Exception as e:
        print("❌ /datos_lavador error:", e)
        return jsonify({'ok': False, 'error': 'server_error'}), 500
# 🔧 FIN PARCHE

@app.route('/logout') 
def logout():
    session.pop('cliente_id', None)
    session.pop('lavador_id', None)
    session.pop('admin', None)
    return redirect('/')

@app.route('/actualizar_ubicacion', methods=['POST'])
def actualizar_ubicacion():
    lavador_id = session.get('lavador_id')
    if not lavador_id:
        print("🚨 Error: No se detecta lavador en sesión.")
        return jsonify({'error': 'No autorizado'}), 401

    data = request.get_json()
    if not data:
        print("🚨 Error: No se recibieron datos de ubicación.")
        return jsonify({'error': 'No se proporcionaron datos'}), 400

    latitud = data.get('latitud')
    longitud = data.get('longitud')

    if latitud is None or longitud is None:
        print("🚨 Error: Datos incompletos de ubicación.")
        return jsonify({'error': 'Faltan datos de ubicación'}), 400

    lavador = Usuario.query.get(lavador_id)
    if lavador:
        lavador.latitud = latitud
        lavador.longitud = longitud
        db.session.commit()
        print(f"📍 Lavador actualizado: latitud={latitud}, longitud={longitud}")
        print("✅ Ubicación actualizada correctamente en la base de datos.")
        return jsonify({'success': True}), 200

    print("🚨 Error: Lavador no encontrado en la base de datos.")
    return jsonify({'error': 'Lavador no encontrado'}), 404

@app.route('/actualizar_ubicacion_cliente', methods=['POST'])
def actualizar_ubicacion_cliente():
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No se proporcionaron datos'}), 400

    latitud = data.get('latitud')
    longitud = data.get('longitud')

    if latitud is None or longitud is None:
        return jsonify({'error': 'Faltan datos de ubicación'}), 400

    cliente = Usuario.query.get(session['usuario_id'])
    if cliente:
        cliente.latitud = latitud
        cliente.longitud = longitud
        db.session.commit()
        print(f"📍 Cliente actualizado: latitud={latitud}, longitud={longitud}")
        return jsonify({'success': True}), 200

    return jsonify({'error': 'Cliente no encontrado'}), 404

@app.route('/solicitar_servicio', methods=['POST'])
def solicitar_servicio():
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({'error': 'No se ha detectado el ID del cliente.'}), 400

    print(f'🧩 Cliente solicitando servicio, ID: {cliente_id}')

    cliente = Usuario.query.get(cliente_id)
    if not cliente:
        return jsonify({'error': 'Cliente no encontrado.'}), 404

    # ⚠️ Verificar ubicación válida
    if not cliente.latitud or not cliente.longitud:
        print("❌ Cliente sin ubicación registrada.")
        return jsonify({'error': 'Ubicación del cliente no disponible.'}), 400

    print(f"🌍 Ubicación del cliente: {cliente.latitud}, {cliente.longitud}")

    nueva_solicitud = Solicitud(
        cliente_id=cliente.id,
        estado='pendiente',
        latitud=cliente.latitud,
        longitud=cliente.longitud
    )
    db.session.add(nueva_solicitud)
    # 🔧 INICIO PARCHE: commit→emit + fallback a todos los lavadores si no hay sesión
    db.session.commit()  # primero confirmar en BD

    lavador_id = session.get('lavador_id')
    lavador = Usuario.query.get(lavador_id) if lavador_id else None

    payload = {
        'solicitud_id': nueva_solicitud.id,
        'cliente_id': cliente.id,
        'lavador_id': lavador.id if lavador else None,
        'nombre': cliente.nombre,
        'apellido': cliente.apellido,
        'telefono': cliente.telefono,
        'latitud': getattr(cliente, 'latitud', None),
        'longitud': getattr(cliente, 'longitud', None)
    }

    if lavador:
        print(f"🚀 Enviando solicitud {nueva_solicitud.id} a lavador_{lavador.id}")
        socketio.emit('nueva_solicitud', payload, room=f"lavador_{lavador.id}")
    else:
        print("⚠️ No hay lavador en sesión; enviando a todos los lavadores.")
        try:
            lavadores = Usuario.query.filter_by(rol='lavador').all()
        except Exception as e:
            print("⚠️ No se pudo listar lavadores:", e)
            lavadores = []
        for lav in lavadores:
            socketio.emit('nueva_solicitud', {**payload, 'lavador_id': lav.id}, room=f"lavador_{lav.id}")
            print(f"📡 Replicada solicitud {nueva_solicitud.id} a lavador_{lav.id}")

    print(f'✅ Solicitud creada con ID {nueva_solicitud.id}')
    return jsonify({'success': 'Solicitud enviada correctamente.', 'solicitud_id': nueva_solicitud.id})
    # 🔧 FIN PARCHE

@app.route('/solicitudes_activas')
def solicitudes_activas():
    solicitudes = Solicitud.query.filter_by(estado='pendiente').all()
    resultado = []
    for solicitud in solicitudes:
        cliente = Usuario.query.get(solicitud.cliente_id)
        if cliente:
            resultado.append({
                'solicitud_id': solicitud.id,
                'nombre': cliente.nombre,
                'apellido': cliente.apellido,
                'telefono': cliente.telefono
            })
    return jsonify(resultado)

@app.route('/aceptar_solicitud')
def aceptar_solicitud():
    if 'lavador_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    solicitud_id = request.args.get('solicitud_id')
    if not solicitud_id:
        return jsonify({'error': 'ID de solicitud no proporcionado'}), 400

    solicitud = Solicitud.query.get(solicitud_id)
    if not solicitud:
        return jsonify({'error': 'Solicitud no encontrada'}), 404

    if solicitud.estado != 'pendiente':
        return jsonify({'error': 'La solicitud ya fue gestionada'}), 400

    lavador = Usuario.query.get(session['lavador_id'])  # ✅ cambio aquí
    if not lavador:
        return jsonify({'error': 'Lavador no encontrado'}), 404

    # Ya no necesitas volver a poner esto:
    # session['lavador_id'] = lavador.id

    # ✅ Asignar el lavador a la solicitud
    solicitud.lavador_id = lavador.id
    solicitud.estado = 'aceptado'
    db.session.commit()
    
    socketio.emit("nueva_solicitud_aceptada", {
        'lavador_id': lavador.id,
        'cliente_id': solicitud.cliente_id
    })

    cliente = Usuario.query.get(solicitud.cliente_id)
    if cliente:
        socketio.emit('notificacion_cliente', {
            'cliente_id': cliente.id,
            'mensaje': f'El lavador ha aceptado tu solicitud y va en camino.'
        })  
        
    print(f"🧩 Solicitud {solicitud_id} aceptada por lavador {lavador.id}")

    return jsonify({'message': 'Solicitud aceptada correctamente.'})

@app.route('/iniciar_movimiento_manual', methods=['POST'])
def iniciar_movimiento_manual():
    data = request.get_json()
    cliente_id = data.get('cliente_id')
    lavador_id = data.get('lavador_id')

    socketio.emit('iniciar_movimiento', {
        'cliente_id': cliente_id,
        'lavador_id': lavador_id
    })
    print(f"✅ Movimiento iniciado manualmente entre cliente {cliente_id} y lavador {lavador_id}")
    return jsonify({'ok': True})

@app.route("/obtener_ids_por_solicitud")
def obtener_ids_por_solicitud():
    solicitud_id = request.args.get("solicitud_id")
    solicitud = Solicitud.query.get(solicitud_id)

    if solicitud:
        return jsonify({
            "cliente_id": solicitud.cliente_id,
            "lavador_id": solicitud.lavador_id
        })
    return jsonify({"error": "Solicitud no encontrada"}), 404

@app.route('/admin_solicitudes')
def admin_solicitudes():
    solicitudes = Solicitud.query.all()
    for s in solicitudes:
        cliente = Usuario.query.get(s.cliente_id)
        lavador = Usuario.query.get(s.lavador_id)
        s.cliente_nombre = cliente.nombre if cliente else '---'
        s.cliente_apellido = cliente.apellido if cliente else ''
        s.lavador_nombre = lavador.nombre if lavador else '---'
        s.lavador_apellido = lavador.apellido if lavador else ''
    return render_template('admin_solicitudes.html', solicitudes=solicitudes)

@app.route('/lavadores_activos')
def lavadores_activos():
    lavadores = Usuario.query.filter_by(rol='lavador', estado='activo').all()
    return render_template('admin_lavadores.html', lavadores=lavadores)

@app.route('/admin_lavadores')
def admin_lavadores():
    lavadores_activos = Usuario.query.filter(
        Usuario.rol == 'lavador',
        Usuario.estado == 'activo',
        Usuario.suscrito == True
    ).all()

    if not lavadores_activos:
        return render_template('admin_lavadores.html', lavadores=[])

    return render_template('admin_lavadores.html', lavadores=lavadores_activos)

@app.route('/cambiar_estado', methods=['POST'])
def cambiar_estado():
    if 'lavador_id' not in session:
        return 'No autorizado', 403

    data = request.get_json()
    nuevo_estado = data.get('estado')

    lavador = Usuario.query.get(session['lavador_id'])
    if lavador:
        lavador.estado = nuevo_estado
        db.session.commit()

        print(f"✅ Estado del lavador {lavador.id} actualizado a: {nuevo_estado}")
        return 'Estado actualizado'
    return 'Lavador no encontrado', 404

@app.route('/obtener_ubicacion_lavador')
def obtener_ubicacion_lavador():
    user_id = request.args.get('user_id')
    lavador = Usuario.query.get(user_id)

    if lavador and lavador.latitud and lavador.longitud:
        return jsonify({'lat': lavador.latitud, 'lng': lavador.longitud})
    
    # Retornar valores nulos en vez de 404 para no romper fetch
    return jsonify({'lat': None, 'lng': None})

@app.route('/obtener_ubicacion_cliente')
def obtener_ubicacion_cliente():
    lavador_id = session.get('lavador_id')
    if not lavador_id:
        print("❌ El usuario no es un lavador")
        return "Acceso denegado", 403

    solicitud = Solicitud.query.filter_by(lavador_id=lavador_id, estado='aceptado').first()
    if not solicitud:
        print("❌ No hay solicitud aceptada para este lavador")
        return jsonify({"error": "No hay solicitud activa"}), 404

    cliente = Usuario.query.get(solicitud.cliente_id)
    if cliente and cliente.latitud and cliente.longitud:
        print(f"📍 Cliente localizado en lat: {cliente.latitud}, lng: {cliente.longitud}")
        return jsonify({"lat": cliente.latitud, "lng": cliente.longitud})
    
    print("❌ No se pudo obtener la ubicación del cliente")
    return jsonify({"error": "Ubicación no disponible"}), 404

@app.route('/finalizar_servicio', methods=['POST'])
def finalizar_servicio():
    data = request.get_json()
    calificacion = data.get('calificacion')
    comentario = data.get('comentario')

    cliente_id = session.get("cliente_id")
    solicitud = Solicitud.query.filter_by(cliente_id=cliente_id, estado='aceptado').first()

    if solicitud:
        solicitud.estado = 'finalizado'
        solicitud.calificacion = calificacion
        solicitud.comentario = comentario

        # También guardar en tabla Calificacion (para el panel del admin)
        nueva_calificacion = Calificacion(
            cliente_id=solicitud.cliente_id,
            lavador_id=solicitud.lavador_id,
            calificacion=calificacion,
            comentario=comentario
        )
        db.session.add(nueva_calificacion)

        db.session.commit()
        return jsonify({'mensaje': 'Servicio finalizado y calificado'})

    return jsonify({'mensaje': 'Solicitud no encontrada'}), 404

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        password = request.form['password']

        # Aquí defines tú mismo la clave secreta del admin
        admin_usuario = 'Angeloaa'
        admin_password = 'Angelo123000'

        if usuario == admin_usuario and password == admin_password:
            session['admin'] = True
            return redirect('/admin_dashboard')
        else:
            return '❌ Usuario o contraseña incorrectos. Intenta de nuevo.'
    return render_template('admin_login.html')

@app.route('/admin_logout')
def admin_logout():
    session.pop('admin', None)
    return render_template('admin_logout.html')

@app.route('/cancelar_solicitud', methods=["POST"])
def cancelar_solicitud():
    cliente_id = session.get("cliente_id")
    if not cliente_id:
        return jsonify({'message': 'No hay cliente en sesión'}), 401

    solicitud = Solicitud.query.filter(
        Solicitud.cliente_id == cliente_id,
        Solicitud.estado != 'finalizado'
    ).first()

    if solicitud:
        lavador = Usuario.query.get(solicitud.lavador_id)
        cliente = Usuario.query.get(solicitud.cliente_id)

        db.session.delete(solicitud)
        db.session.commit()

        if lavador:
            socketio.emit('notificacion_lavador', {
                'titulo': 'Solicitud cancelada',
                'mensaje': f'El cliente {cliente.nombre} canceló la solicitud.'
            })

        return jsonify({'message': 'Solicitud cancelada correctamente.'})
    else:
        return jsonify({'message': 'No se encontró una solicitud activa para cancelar.'}), 404

@app.route('/terminos')
def terminos():
    return render_template('terminos.html')

@app.route('/')
def splash():
    return render_template('splash.html')

@app.route('/obtener_ubicacion_cliente_directo')
def obtener_ubicacion_cliente_directo():
    if 'usuario_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401

    cliente = Usuario.query.get(session['usuario_id'])
    if cliente and cliente.rol == 'cliente':
        return jsonify({'lat': cliente.latitud, 'lng': cliente.longitud})
    
    return jsonify({'error': 'Cliente no encontrado'}), 404


# 🔧 INICIO PARCHE UNION SALA (SERVIDOR)
@socketio.on("unirse_sala_privada")
def manejar_union_sala(data):
    lavador_id = data.get("lavador_id")
    if not lavador_id:
        emit("union_error", {"motivo": "lavador_id vacío"})
        return
    try:
        lavador_id = int(lavador_id)  # por si viene como string
    except Exception:
        pass

    room = f"lavador_{lavador_id}"
    join_room(room)
    print(f"🔒 Lavador {lavador_id} unido a sala privada")
    emit("union_confirmada", {"sala": room})
# 🔧 FIN PARCHE UNION SALA (SERVIDOR)

@socketio.on("enviar_mensaje_privado")
def manejar_mensaje_privado(data):
    if not all(k in data for k in ("cliente_id", "lavador_id", "autor_id", "mensaje")):
        print("❌ Datos incompletos en el mensaje:", data)
        return

    cliente_id = data["cliente_id"]
    lavador_id = data["lavador_id"]
    autor_id = data["autor_id"]
    mensaje = data["mensaje"]
    sala = f"chat_{min(cliente_id, lavador_id)}_{max(cliente_id, lavador_id)}"

    # Emitir mensaje en tiempo real
    emit("recibir_mensaje_privado", {
        "mensaje": mensaje,
        "autor_id": autor_id
    }, room=sala)

    # Enviar también al usuario directo para notificación
    destinatario_id = lavador_id if autor_id == cliente_id else cliente_id
    emitir_mensaje_directo(destinatario_id, mensaje)

    # Guardar mensaje en la base de datos
    nuevo = Mensaje(
        de_id=autor_id,
        para_id=destinatario_id,
        texto=mensaje
    )
    db.session.add(nuevo)

    # Marcar solicitud como con mensajes nuevos si existe
    solicitud = Solicitud.query.filter(
        ((Solicitud.cliente_id == cliente_id) & (Solicitud.lavador_id == lavador_id)) |
        ((Solicitud.cliente_id == lavador_id) & (Solicitud.lavador_id == cliente_id)),
        Solicitud.estado == 'aceptado'
    ).first()

    if solicitud:
        solicitud.tiene_mensajes_nuevos = True

    db.session.commit()

@socketio.on('connect')
def handle_connect():
    user_id = request.args.get('user_id')
    if user_id:
        join_room(user_id)

@socketio.on("solicitud_cliente")
def manejar_solicitud_cliente(data):
    print("📥 Solicitud recibida del cliente:", data)

    cliente_id = data.get("cliente_id")
    latitud = data.get("latitud")
    longitud = data.get("longitud")

    if not cliente_id or not latitud or not longitud:
        print("❌ Datos incompletos para crear la solicitud")
        return

    cliente = Usuario.query.get(cliente_id)
    if not cliente:
        print("❌ Cliente no encontrado en la base de datos")
        return

    solicitud = Solicitud(
        cliente_id=cliente_id,
        latitud=latitud,
        longitud=longitud,
        estado="pendiente"
    )
    db.session.add(solicitud)
    db.session.commit()

    print("✅ Solicitud guardada con ID:", solicitud.id)

    # Emitir a todos los lavadores activos
    datos_emitidos = {
        "solicitud_id": solicitud.id,
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "apellido": cliente.apellido,
        "telefono": cliente.telefono,
        "latitud": latitud,
        "longitud": longitud,
    }

    lavador_id = data.get("lavador_id")  # ✅ Asegúrate de obtenerlo desde el front

    if not lavador_id:
        print("❌ lavador_id faltante en data")
        return

    socketio.emit("nueva_solicitud", datos_emitidos, room=f"lavador_{lavador_id}")
    print(f"📡 Solicitud emitida a lavador_{lavador_id}:", datos_emitidos)

@socketio.on("actualizar_ubicacion_cliente")
def actualizar_ubicacion_cliente(data):
    cliente_id = data.get("cliente_id")
    lat = data.get("latitud")
    lng = data.get("longitud")

    if cliente_id and lat and lng:
        solicitud = Solicitud.query.filter_by(cliente_id=cliente_id, estado="aceptado").first()
        if solicitud:
            solicitud.latitud = lat
            solicitud.longitud = lng
            db.session.commit()
            print(f"📍 Ubicación actualizada para cliente {cliente_id}: {lat}, {lng}")
            # También podemos emitir al lavador para que se actualice el marcador del cliente
            socketio.emit("actualizar_ubicacion_cliente", {
                "latitud": lat,
                "longitud": lng
            }, room=f"lavador_{solicitud.lavador_id}")

@app.route('/chat')  
def chat():
    rol = request.args.get('rol')

    if rol == 'cliente':
        cliente_id = session.get('cliente_id')
        if cliente_id:
            cliente = Usuario.query.get(cliente_id)
            solicitud = Solicitud.query.filter_by(cliente_id=cliente.id, estado='aceptado').first()

            if solicitud:
                lavador = Usuario.query.get(solicitud.lavador_id)
                sala = f"chat_{min(cliente.id, lavador.id)}_{max(cliente.id, lavador.id)}"
                titulo_chat = f"Chat con {lavador.nombre} (Lavador)"

                return render_template(
                    'chat.html',
                    cliente=cliente,
                    lavador=lavador,
                    rol='cliente',
                    titulo_chat=titulo_chat,
                    sala=sala
                )

        # ❌ Si no hay solicitud válida, redirigir
        return redirect('/cliente_dashboard')

    elif rol == 'lavador':
        lavador_id = session.get('lavador_id')
        if lavador_id:
            lavador = Usuario.query.get(lavador_id)
            solicitud = Solicitud.query.filter_by(lavador_id=lavador.id, estado='aceptado').first()

            if solicitud:
                cliente = Usuario.query.get(solicitud.cliente_id)
                sala = f"chat_{min(cliente.id, lavador.id)}_{max(cliente.id, lavador.id)}"
                titulo_chat = f"Chat con {cliente.nombre} (Cliente)"

                return render_template(
                    'chat.html',
                    cliente=cliente,
                    lavador=lavador,
                    rol='lavador',
                    titulo_chat=titulo_chat,
                    sala=sala
                )

        # ❌ Si no hay solicitud válida, redirigir
        return redirect('/lavador_dashboard')

    return redirect('/')

@app.route('/solicitud_activa')
def obtener_solicitud_activa():
    lavador_id = request.args.get('lavador_id') or session.get('usuario_id')
    if not lavador_id:
        return jsonify({})
    
    solicitud = Solicitud.query.filter_by(lavador_id=lavador_id, estado='aceptado').first()
    if solicitud:
        return jsonify({
            'estado': solicitud.estado,
            'cliente_id': solicitud.cliente_id,
            'lavador_id': solicitud.lavador_id
        })
    return jsonify({})

@app.route('/activar_admin')
def activar_admin():
    admin = Usuario.query.filter_by(rol='admin').first()
    if admin:
        session.clear()
        session['usuario_id'] = admin.id
        print(f"✅ Admin activado en sesión: {admin.nombre} (ID: {admin.id})")
        return redirect(url_for('admin_dashboard'))
    return "❌ No se encontró un usuario con rol admin."

@app.route('/ver_calificaciones/<int:lavador_id>')
def ver_calificaciones(lavador_id):
    calificaciones = Solicitud.query.filter_by(lavador_id=lavador_id).filter(Solicitud.calificacion != None).all()
    resultado = []
    for c in calificaciones:
        cliente = Usuario.query.get(c.cliente_id)
        resultado.append({
            'nombre': cliente.nombre,
            'apellido': cliente.apellido,
            'calificacion': c.calificacion,
            'comentario': c.comentario or ""
        })
    return jsonify(resultado)

@app.route('/verificar_mensajes_nuevos')
def verificar_mensajes_nuevos():
    usuario_id = session.get('cliente_id') or session.get('lavador_id')
    if not usuario_id:
        return jsonify({'mensajes_nuevos': False})
    
    if 'cliente_id' in session:
        solicitud = Solicitud.query.filter_by(cliente_id=usuario_id, estado='aceptado').first()
    else:
        solicitud = Solicitud.query.filter_by(lavador_id=usuario_id, estado='aceptado').first()

    if solicitud and solicitud.tiene_mensajes_nuevos:
        return jsonify({'mensajes_nuevos': True})
    return jsonify({'mensajes_nuevos': False})

@app.route("/mensajes_chat/<int:cliente_id>/<int:lavador_id>")
def mensajes_chat(cliente_id, lavador_id):
    mensajes = Mensaje.query.filter(
        ((Mensaje.de_id == cliente_id) & (Mensaje.para_id == lavador_id)) |
        ((Mensaje.de_id == lavador_id) & (Mensaje.para_id == cliente_id))
    ).order_by(Mensaje.timestamp).all()
    
    return jsonify([
        {
            "autor_id": m.de_id,
            "mensaje": m.texto,
            "timestamp": m.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        } for m in mensajes
    ])

@app.route('/seleccion_rol')
def seleccion_rol_redirigir():
    session.clear()
    return redirect('/')

@app.route('/admin_calificaciones')
def admin_calificaciones():
    calificaciones = Calificacion.query.order_by(Calificacion.timestamp.desc()).all()

    datos = []
    for c in calificaciones:
        cliente = Usuario.query.get(c.cliente_id) if c.cliente_id else None
        lavador = Usuario.query.get(c.lavador_id) if c.lavador_id else None
        datos.append({
            'cliente_nombre': f"{cliente.nombre} {cliente.apellido}" if cliente else "Desconocido",
            'lavador_nombre': f"{lavador.nombre} {lavador.apellido}" if lavador else "Desconocido",
            'calificacion': c.calificacion,
            'comentario': c.comentario or "",
            'timestamp': c.timestamp
        })

    return render_template('admin_calificaciones.html', calificaciones=datos)

@app.route("/solicitudes_pendientes")
def solicitudes_pendientes():
    pendientes = Solicitud.query.filter_by(estado="pendiente").all()
    resultado = []
    for s in pendientes:
        cliente = Usuario.query.get(s.cliente_id)
        resultado.append({
            "solicitud_id": s.id,
            "cliente_id": cliente.id,
            "nombre": cliente.nombre,
            "apellido": cliente.apellido,
            "telefono": cliente.telefono,
            "latitud": s.latitud,
            "longitud": s.longitud
        })
    return jsonify(resultado)

@app.route('/actualizar_ubicacion_lavador')
def actualizar_ubicacion_lavador():
    user_id = session.get("lavador_id")
    if not user_id:
        return jsonify({"error": "Lavador no autenticado"}), 401

    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)

    if lat is None or lng is None:
        return jsonify({"error": "Coordenadas inválidas"}), 400

    lavador = Usuario.query.get(user_id)
    if lavador:
        lavador.latitud = lat
        lavador.longitud = lng
        db.session.commit()
        return jsonify({"success": True})

    return jsonify({"error": "Lavador no encontrado"}), 404
    
@app.get("/debug_emit/<int:lavador_id>")
def debug_emit(lavador_id):
    payload = {
        "lavador_id": lavador_id,
        "cliente_id": 999999,
        "nombre": "Debug",
        "apellido": "Test",
        "telefono": "000-000-0000"
    }
    socketio.emit("nueva_solicitud", payload, room=f"lavador_{lavador_id}")
    return {"ok": True, "room": f"lavador_{lavador_id}"}
    
@app.after_request
def add_no_cache_headers(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0, private"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

APP_VERSION = "2025-08-06-02"  # <-- súbele 1 si vuelves a desplegar

@app.get("/__version")
def version():
    return {"version": APP_VERSION}

# 🔧 INICIO PARCHE: endpoint para verificar versiones en producción
@app.route('/_versions')
def _versions():
    import sys, flask_socketio, socketio, engineio, eventlet
    return jsonify({
        "python": sys.version,
        "flask_socketio": flask_socketio.__version__,
        "python_socketio": socketio.__version__,
        "engineio": engineio.__version__,
        "eventlet": eventlet.__version__
    }), 200
# 🔧 FIN PARCHE

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    socketio.run(app, host="0.0.0.0", port=port, debug=IS_WINDOWS)
