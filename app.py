# -*- coding: utf-8 -*-

import os
import csv
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, jsonify, Blueprint, Response
from flask_sqlalchemy import SQLAlchemy
# CORREÇÃO: Removido 'Room' da importação
from flask_socketio import SocketIO, join_room, leave_room, send, emit 
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
from sqlalchemy import or_, func, and_
from sqlalchemy.orm import joinedload
from flask_migrate import Migrate
from flask_mail import Mail, Message
from celery import Celery
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature

# --- Configuração da Aplicação ---
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
# Carrega a configuração do arquivo config.py
app.config.from_object('config.Config')

# Serializer para tokens de redefinição de senha
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# --- Configuração do Celery ---
def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

# --- Inicialização das Extensões ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
socketio = SocketIO(app)
mail = Mail(app)
celery = make_celery(app)

# --- Constantes (Carregadas do app.config) ---
UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
ATTACHMENT_FOLDER = app.config['ATTACHMENT_FOLDER']
CHAT_ATTACHMENT_FOLDER = app.config['CHAT_ATTACHMENT_FOLDER']
ALLOWED_IMG_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_ATTACH_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png'}


# --- Funções de E-mail Assíncrono (com Celery) ---
@celery.task
def send_async_email(subject, recipients, html_body):
    """Tarefa Celery para enviar e-mail."""
    msg = Message(subject, recipients=recipients, html=html_body)
    with app.app_context():
        try:
            mail.send(msg)
            print(f"E-mail enviado para {recipients}")
        except Exception as e:
            print(f"Erro ao enviar e-mail: {e}")

def send_email(subject, recipients, html_body):
    """Chama a tarefa Celery de forma assíncrona."""
    send_async_email.delay(subject, recipients, html_body)


# --- Funções Auxiliares e Decoradores ---
def allowed_file(filename, allowed_set): return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'company_id' not in session: flash('Você precisa estar logado.', 'error'); return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'): flash('Acesso restrito a administradores.', 'error'); return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function
def supplier_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_type') != 'supplier': flash('Acesso negado a esta área.', 'error'); return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function
@app.context_processor
def inject_notifications():
    if 'company_id' in session:
        unread_count = db.session.query(Notification).filter_by(recipient_id=session['company_id'], read=False).count()
        cart_item_count = len(session.get('cart', {})) if session.get('user_type') == 'buyer' else 0
        return dict(unread_notifications=unread_count, cart_item_count=cart_item_count)
    return dict(unread_notifications=0, cart_item_count=0)

# --- Modelos do Banco de Dados ---
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True); company_name = db.Column(db.String(150), nullable=False); cnpj = db.Column(db.String(18), unique=True, nullable=False); email = db.Column(db.String(150), unique=True, nullable=False); password_hash = db.Column(db.String(256), nullable=False); user_type = db.Column(db.String(50), nullable=False)
    is_verified = db.Column(db.Boolean, default=False); is_admin = db.Column(db.Boolean, default=False); is_active = db.Column(db.Boolean, default=True)
    logo_filename = db.Column(db.String(255), nullable=True); description = db.Column(db.Text, nullable=True); website = db.Column(db.String(255), nullable=True); address = db.Column(db.String(255), nullable=True); certifications = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    products = db.relationship('Product', backref='supplier', lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship('Notification', foreign_keys='Notification.recipient_id', backref='recipient', lazy=True, cascade="all, delete-orphan")
    reviews_received = db.relationship('Review', foreign_keys='Review.supplier_id', backref='reviewed_supplier', lazy='dynamic')
    sent_quotes = db.relationship('QuoteRequest', foreign_keys='QuoteRequest.buyer_id', backref='buyer', lazy='dynamic')
    received_quotes = db.relationship('QuoteRequest', foreign_keys='QuoteRequest.supplier_id', backref='supplier', lazy='dynamic')
    quote_groups = db.relationship('QuoteGroup', backref='buyer', lazy=True)
    open_rfqs = db.relationship('OpenRFQ', backref='buyer', lazy=True) # RFQ: Ligação com a empresa que criou
    open_rfq_responses = db.relationship('OpenRFQResponse', backref='supplier', lazy=True) # RFQ: Ligação com as respostas
    def set_password(self,p): self.password_hash=generate_password_hash(p)
    def check_password(self,p): return check_password_hash(self.password_hash,p)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True); name = db.Column(db.String(100), nullable=False); description = db.Column(db.Text, nullable=False); category = db.Column(db.String(80), nullable=False); base_price = db.Column(db.Float, nullable=True); supplier_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    images = db.relationship('ProductImage', backref='product', lazy=True, cascade="all, delete-orphan")
    quote_requests = db.relationship('QuoteRequest', backref='product', lazy=True, cascade="all, delete-orphan")

class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True); filename = db.Column(db.String(255), nullable=False); product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)

class QuoteRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True); quantity = db.Column(db.Integer, nullable=False); message = db.Column(db.Text, nullable=True); status = db.Column(db.String(50), nullable=False, default='Pendente'); timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False); buyer_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False); supplier_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    offered_price = db.Column(db.Float, nullable=True); supplier_message = db.Column(db.Text, nullable=True); response_timestamp = db.Column(db.DateTime, nullable=True)
    attachment_filename = db.Column(db.String(255), nullable=True); delivery_date = db.Column(db.Date, nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('quote_group.id'), nullable=True)
    review = db.relationship('Review', backref='quote', uselist=False, cascade="all, delete-orphan")
    chat_messages = db.relationship('ChatMessage', backref='quote', lazy=True, cascade="all, delete-orphan")

class QuoteGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    buyer_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    quotes = db.relationship('QuoteRequest', backref='group', lazy='dynamic')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True); message = db.Column(db.String(255), nullable=False); link = db.Column(db.String(255), nullable=True); timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow); read = db.Column(db.Boolean, default=False); recipient_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True); rating = db.Column(db.Integer, nullable=False); comment = db.Column(db.Text, nullable=True); timestamp = db.Column(db.DateTime, default=datetime.utcnow); quote_id = db.Column(db.Integer, db.ForeignKey('quote_request.id'), unique=True, nullable=False); reviewer_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False); supplier_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True); message = db.Column(db.Text, nullable=True); timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False); quote_id = db.Column(db.Integer, db.ForeignKey('quote_request.id'), nullable=False); sender_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    attachment_filename = db.Column(db.String(255), nullable=True) # Campo para anexo
    attachment_type = db.Column(db.String(50), nullable=True) # Tipo do anexo (imagem, pdf, etc.)
    sender = db.relationship('Company')

# --- NOVOS MODELOS PARA RFQ ABERTO ---
class OpenRFQ(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    quantity = db.Column(db.String(50), nullable=False) # Usando String para flexibilidade (ex: "100 unidades", "500 metros")
    deadline = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), default='Aberto') # Aberto, Fechado
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    buyer_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    responses = db.relationship('OpenRFQResponse', backref='rfq', lazy='dynamic', cascade="all, delete-orphan")

class OpenRFQResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    price = db.Column(db.Float, nullable=False)
    delivery_date = db.Column(db.Date, nullable=True)
    message = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    rfq_id = db.Column(db.Integer, db.ForeignKey('open_rfq.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
# --- FIM DOS NOVOS MODELOS ---

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- Comandos CLI ---
@app.cli.command("create-admin")
def create_admin():
    email = input("Digite o e-mail do administrador: "); password = input("Digite a senha: ")
    company_name = input("Digite o nome da empresa/admin: "); cnpj = input("Digite um CNPJ (pode ser fictício): ")
    if Company.query.filter_by(email=email).first(): print("Erro: E-mail já existe."); return
    admin_user = Company(email=email, company_name=company_name, cnpj=cnpj, user_type='admin', is_admin=True, is_verified=True); admin_user.set_password(password)
    db.session.add(admin_user); db.session.commit()
    print(f"Administrador '{email}' criado com sucesso!")

# --- Rotas Principais ---
@app.route('/')
def home():
    if 'company_id' in session:
        if session.get('is_admin'): return redirect(url_for('admin.index'))
        else: return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/public_home')
def public_home():
    return render_template('index.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if 'company_id' in session: return redirect(url_for('home'))
    if request.method == 'POST':
        email = request.form.get('email'); password = request.form.get('password')
        company = Company.query.filter_by(email=email).first()
        if company and company.check_password(password):
            if not company.is_active: flash('Esta conta foi suspensa.', 'error'); return redirect(url_for('login'))
            session['company_id'] = company.id; session['company_name'] = company.company_name; session['user_type'] = company.user_type; session['is_admin'] = company.is_admin
            if company.is_admin: return redirect(url_for('admin.index'))
            return redirect(url_for('dashboard'))
        else: flash('E-mail ou senha inválidos.', 'error'); return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        company_name=request.form.get('company_name'); cnpj=request.form.get('cnpj'); email=request.form.get('email'); password=request.form.get('password'); user_type=request.form.get('user_type')
        if not all([company_name, cnpj, email, password, user_type]): flash('Todos os campos são obrigatórios.', 'error'); return redirect(url_for('register'))
        if Company.query.filter_by(email=email).first(): flash('Este e-mail já está cadastrado.', 'error'); return redirect(url_for('register'))
        if Company.query.filter_by(cnpj=cnpj).first(): flash('Este CNPJ já está cadastrado.', 'error'); return redirect(url_for('register'))
        new_company=Company(company_name=company_name, cnpj=cnpj, email=email, user_type=user_type); new_company.set_password(password)
        db.session.add(new_company); db.session.commit(); flash('Empresa cadastrada com sucesso! Faça o login.', 'success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout(): session.clear(); flash('Você saiu da sua conta.','success'); return redirect(url_for('home'))

# --- ROTAS DE RECUPERAÇÃO DE SENHA ---
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if session.get('company_id'):
        return redirect(url_for('home'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        company = Company.query.filter_by(email=email).first()
        
        if company:
            # Gerar token (válido por 1800 segundos = 30 minutos)
            token = s.dumps(email, salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            
            html_body = render_template(
                'email/reset_password.html',
                company_name=company.company_name,
                reset_url=reset_url
            )
            
            send_email(
                subject="Recuperação de Senha - Connecta B2B",
                recipients=[company.email],
                html_body=html_body
            )
            
            flash('Um link de recuperação foi enviado para o seu e-mail.', 'success')
            return redirect(url_for('login'))
        else:
            flash('E-mail não encontrado em nosso cadastro.', 'error')
            return redirect(url_for('forgot_password'))
            
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if session.get('company_id'):
        return redirect(url_for('home'))
        
    try:
        # Verificar o token (validade de 30 minutos = 1800s)
        email = s.loads(token, salt='password-reset-salt', max_age=1800)
    except SignatureExpired:
        flash('O link de recuperação expirou. Por favor, solicite um novo.', 'error')
        return redirect(url_for('forgot_password'))
    except BadTimeSignature:
        flash('Link de recuperação inválido.', 'error')
        return redirect(url_for('forgot_password'))
    except Exception:
        flash('Link de recuperação inválido.', 'error')
        return redirect(url_for('forgot_password'))

    company = Company.query.filter_by(email=email).first()
    if not company:
        flash('Usuário não encontrado.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        new_password = request.form.get('password')
        if not new_password or len(new_password) < 8:
            flash('A senha deve ter pelo menos 8 caracteres.', 'error')
            return redirect(url_for('reset_password', token=token))
            
        company.set_password(new_password)
        db.session.commit()
        
        flash('Sua senha foi redefinida com sucesso! Você já pode fazer o login.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html')
# --- FIM DAS ROTAS DE RECUPERAÇÃO DE SENHA ---

@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('is_admin'): return redirect(url_for('admin.index'))
    company = db.session.get(Company, session['company_id'])
    view = request.args.get('view', 'active')
    active_announcement = Announcement.query.filter_by(is_active=True).order_by(Announcement.timestamp.desc()).first()
    analytics = {}
    if company.user_type == 'supplier':
        quotes_query = company.received_quotes
        active_quotes = quotes_query.filter(or_(QuoteRequest.status == 'Pendente', QuoteRequest.status == 'Respondido')).order_by(QuoteRequest.timestamp.desc()).all()
        archived_quotes = quotes_query.filter(or_(QuoteRequest.status == 'Aceito', QuoteRequest.status == 'Recusado')).order_by(QuoteRequest.timestamp.desc()).all()
        analytics['total_quotes'] = quotes_query.count(); analytics['accepted_quotes'] = quotes_query.filter_by(status='Aceito').count(); analytics['acceptance_rate'] = (analytics['accepted_quotes'] / analytics['total_quotes'] * 100) if analytics['total_quotes'] > 0 else 0; analytics['avg_rating'] = db.session.query(func.avg(Review.rating)).filter(Review.supplier_id == company.id).scalar() or 0
        return render_template('dashboard.html', products=company.products, active_quotes=active_quotes, archived_quotes=archived_quotes, view=view, analytics=analytics, active_announcement=active_announcement)
    elif company.user_type == 'buyer':
        quote_groups = QuoteGroup.query.filter_by(buyer_id=company.id).order_by(QuoteGroup.timestamp.desc()).all()
        analytics['total_sent'] = company.sent_quotes.count(); analytics['total_accepted'] = company.sent_quotes.filter_by(status='Aceito').count()
        return render_template('dashboard.html', quote_groups=quote_groups, view=view, analytics=analytics, active_announcement=active_announcement)
    return redirect(url_for('home'))

@app.route('/chat/<int:quote_id>')
@login_required
def chat(quote_id):
    quote = db.session.get(QuoteRequest, quote_id)
    if session['company_id'] not in [quote.buyer_id, quote.supplier_id]: flash('Acesso não permitido.', 'error'); return redirect(url_for('dashboard'))
    messages = ChatMessage.query.filter_by(quote_id=quote.id).order_by(ChatMessage.timestamp.asc()).all()
    return render_template('chat.html', quote=quote, messages=messages)

# --- NOVAS ROTAS PARA RFQ ABERTO ---
@app.route('/rfq/open/new', methods=['GET', 'POST'])
@login_required
def new_open_rfq():
    if session.get('user_type') != 'buyer':
        flash('Apenas compradores podem criar RFQs.', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        quantity = request.form.get('quantity')
        deadline_str = request.form.get('deadline')
        deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date() if deadline_str else None
        
        if not all([title, description, category, quantity]):
            flash('Todos os campos são obrigatórios.', 'error')
            return redirect(url_for('new_open_rfq'))

        new_rfq = OpenRFQ(
            title=title, description=description, category=category,
            quantity=quantity, deadline=deadline, buyer_id=session['company_id']
        )
        db.session.add(new_rfq)
        db.session.commit()
        flash('Sua solicitação de cotação aberta foi publicada!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('new_open_rfq.html')

@app.route('/rfq/open')
@login_required
def list_open_rfqs():
    if session.get('user_type') != 'supplier':
        flash('Apenas fornecedores podem ver esta página.', 'error')
        return redirect(url_for('dashboard'))
    
    rfqs = OpenRFQ.query.filter_by(status='Aberto').order_by(OpenRFQ.timestamp.desc()).all()
    return render_template('list_open_rfqs.html', rfqs=rfqs)

@app.route('/rfq/open/<int:rfq_id>', methods=['GET', 'POST'])
@login_required
def open_rfq_detail(rfq_id):
    rfq = db.session.get(OpenRFQ, rfq_id)
    if not rfq:
        flash('RFQ não encontrado.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST' and session.get('user_type') == 'supplier':
        price_str = request.form.get('price')
        delivery_date_str = request.form.get('delivery_date')
        message = request.form.get('message')

        if not price_str:
            flash('O preço é obrigatório.', 'error')
            return redirect(url_for('open_rfq_detail', rfq_id=rfq.id))

        price = float(price_str)
        delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d').date() if delivery_date_str else None

        new_response = OpenRFQResponse(
            price=price, delivery_date=delivery_date, message=message,
            rfq_id=rfq.id, supplier_id=session['company_id']
        )
        db.session.add(new_response)
        db.session.commit() # Commit da resposta

        # Notificar o comprador
        notification = Notification(
            message=f"Sua RFQ '{rfq.title}' recebeu uma nova proposta.",
            link=url_for('open_rfq_detail', rfq_id=rfq.id),
            recipient_id=rfq.buyer_id
        )
        db.session.add(notification)
        db.session.commit() # Commit da notificação

        # Emitir notificação em tempo real
        unread_count = db.session.query(Notification).filter_by(recipient_id=rfq.buyer_id, read=False).count()
        socketio.emit('new_notification', 
                      {'unread_count': unread_count}, 
                      room=f"user_{rfq.buyer_id}")
        
        flash('Sua proposta foi enviada!', 'success')
        return redirect(url_for('open_rfq_detail', rfq_id=rfq.id))
        
    return render_template('open_rfq_detail.html', rfq=rfq)
# --- FIM DAS NOVAS ROTAS ---

@app.route('/products')
@login_required
def products():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('search', ''); category_query = request.args.get('category', '')
    price_min = request.args.get('price_min', type=float); price_max = request.args.get('price_max', type=float)
    location_query = request.args.get('location', ''); rating_min = request.args.get('rating_min', type=float)
    query = Product.query.join(Company, Product.supplier_id == Company.id)
    if search_query: query = query.filter(or_(Product.name.ilike(f"%{search_query}%"), Product.description.ilike(f"%{search_query}%")))
    if category_query: query = query.filter(Product.category == category_query)
    if price_min is not None: query = query.filter(Product.base_price >= price_min)
    if price_max is not None: query = query.filter(Product.base_price <= price_max)
    if location_query: query = query.filter(Company.address.ilike(f"%{location_query}%"))
    if rating_min is not None and rating_min > 0:
        avg_ratings = db.session.query(Review.supplier_id, func.avg(Review.rating).label('avg_rating')).group_by(Review.supplier_id).subquery()
        query = query.join(avg_ratings, Product.supplier_id == avg_ratings.c.supplier_id).filter(avg_ratings.c.avg_rating >= rating_min)
    pagination = query.order_by(Product.id.desc()).paginate(page=page, per_page=9)
    categories = db.session.query(Product.category).distinct().all()
    filter_values = {'search': search_query, 'category': category_query, 'price_min': price_min, 'price_max': price_max, 'location': location_query, 'rating_min': rating_min }
    return render_template('products.html', pagination=pagination, categories=[c[0] for c in categories], filters=filter_values)

@app.route('/autocomplete_search')
@login_required
def autocomplete_search():
    query = request.args.get('query', '')
    if len(query) < 2: return jsonify([])
    search_term = f"%{query}%"
    results = Product.query.filter(Product.name.ilike(search_term)).limit(5).all()
    return jsonify([product.name for product in results])

@app.route('/product/<int:product_id>', methods=['GET','POST'])
@login_required
def product_detail(product_id):
    product = db.session.get(Product, product_id)
    return render_template('product_detail.html', product=product)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    if session['user_type'] != 'buyer': flash('Apenas compradores podem usar o carrinho.', 'error'); return redirect(request.referrer)
    cart = session.get('cart', {})
    product = db.session.get(Product, product_id)
    if product:
        cart[str(product_id)] = {'quantity': 1}
        session['cart'] = cart
        flash(f'{product.name} foi adicionado ao carrinho de cotação!', 'success')
    return redirect(url_for('products'))

@app.route('/cart')
@login_required
def view_cart():
    if session['user_type'] != 'buyer': flash('Apenas compradores podem usar o carrinho.', 'error'); return redirect(url_for('dashboard'))
    cart_data = session.get('cart', {})
    products_in_cart = []
    if cart_data:
        product_ids = [int(pid) for pid in cart_data.keys()]
        products = Product.query.filter(Product.id.in_(product_ids)).all()
        for product in products:
            products_in_cart.append({'product': product, 'quantity': cart_data[str(product.id)]['quantity']})
    return render_template('cart.html', cart_items=products_in_cart)

@app.route('/cart/update', methods=['POST'])
@login_required
def update_cart():
    cart = session.get('cart', {})
    for product_id, quantity in request.form.items():
        if product_id.startswith('quantity-') and product_id.split('-')[1] in cart:
            pid = product_id.split('-')[1]
            try: cart[pid]['quantity'] = int(quantity)
            except (ValueError, TypeError): pass
    session['cart'] = cart
    return redirect(url_for('view_cart'))

@app.route('/cart/remove/<int:product_id>', methods=['POST'])
@login_required
def remove_from_cart(product_id):
    cart = session.get('cart', {})
    if str(product_id) in cart:
        del cart[str(product_id)]
        session['cart'] = cart
        flash('Produto removido do carrinho.', 'info')
    return redirect(url_for('view_cart'))

@app.route('/cart/submit', methods=['POST'])
@login_required
def submit_cart_quotes():
    cart_data = session.get('cart', {})
    group_name = request.form.get('group_name')
    if not cart_data: flash('Seu carrinho está vazio.', 'error'); return redirect(url_for('view_cart'))
    if not group_name: flash('O nome do grupo de cotação é obrigatório.', 'error'); return redirect(url_for('view_cart'))
    
    new_group = QuoteGroup(name=group_name, buyer_id=session['company_id'])
    db.session.add(new_group); db.session.flush()

    supplier_notifications = {} # Rastrear fornecedores para notificar

    for product_id, item_data in cart_data.items():
        product = db.session.get(Product, int(product_id))
        if product:
            new_quote = QuoteRequest(quantity=item_data['quantity'], product_id=product.id, buyer_id=session['company_id'], supplier_id=product.supplier_id, group_id=new_group.id)
            db.session.add(new_quote)
            db.session.flush()
            notification = Notification(message=f"Nova cotação para {product.name} (Grupo: {group_name}).", link=url_for('quote_detail', quote_id=new_quote.id), recipient_id=product.supplier_id)
            db.session.add(notification)
            supplier_notifications[product.supplier_id] = True # Marcar fornecedor para notificação

    db.session.commit() # Commit de cotações e notificações

    # Emitir notificações em tempo real para fornecedores
    for supplier_id in supplier_notifications.keys():
        unread_count = db.session.query(Notification).filter_by(recipient_id=supplier_id, read=False).count()
        socketio.emit('new_notification', 
                      {'unread_count': unread_count}, 
                      room=f"user_{supplier_id}")

    session.pop('cart', None)
    flash('Cotações enviadas com sucesso!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/comparator/<int:group_id>')
@login_required
def comparator(group_id):
    group = db.session.get(QuoteGroup, group_id)
    if not group or group.buyer_id != session['company_id']:
        flash('Grupo de cotação não encontrado ou não autorizado.', 'error'); return redirect(url_for('dashboard'))
    quotes = QuoteRequest.query.filter_by(group_id=group.id).options(joinedload(QuoteRequest.product), joinedload(QuoteRequest.supplier)).all()
    supplier_ratings = {}
    for quote in quotes:
        if quote.supplier_id not in supplier_ratings:
            avg_rating = db.session.query(func.avg(Review.rating)).filter(Review.supplier_id == quote.supplier_id).scalar() or 0
            supplier_ratings[quote.supplier_id] = avg_rating
    return render_template('comparator.html', group=group, quotes=quotes, supplier_ratings=supplier_ratings)

@app.route('/uploads/attachments/<filename>')
@login_required
def download_attachment(filename): return send_from_directory(app.config['ATTACHMENT_FOLDER'], filename, as_attachment=True)

@app.route('/uploads/chat/<filename>') # Rota para baixar anexos do chat
@login_required
def download_chat_attachment(filename):
    return send_from_directory(app.config['CHAT_ATTACHMENT_FOLDER'], filename, as_attachment=True)

@app.route('/company/<int:company_id>')
@login_required
def company_profile(company_id):
    company = db.session.get(Company, company_id)
    avg_rating = db.session.query(func.avg(Review.rating)).filter(Review.supplier_id == company.id).scalar()
    reviews = Review.query.filter_by(supplier_id=company_id).order_by(Review.timestamp.desc()).all()
    return render_template('company_profile.html', company=company, avg_rating=avg_rating, reviews=reviews)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    company = db.session.get(Company, session['company_id'])
    if request.method == 'POST':
        company.company_name = request.form.get('company_name'); session['company_name'] = company.company_name
        company.description = request.form.get('description'); company.website = request.form.get('website'); company.address = request.form.get('address'); company.certifications = request.form.get('certifications')
        logo_file = request.files.get('logo')
        if logo_file and allowed_file(logo_file.filename, ALLOWED_IMG_EXTENSIONS):
            filename = secure_filename(f"logo_{company.id}_{logo_file.filename}"); logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename)); company.logo_filename = filename
        db.session.commit(); flash('Perfil atualizado com sucesso!', 'success'); return redirect(url_for('company_profile', company_id=company.id))
    return render_template('edit_profile.html', company=company)

@app.route('/quote/<int:quote_id>/review', methods=['GET', 'POST'])
@login_required
def add_review(quote_id):
    quote = db.session.get(QuoteRequest, quote_id)
    if quote.buyer_id != session.get('company_id') or quote.status != 'Aceito' or quote.review:
        flash('Não é possível avaliar esta cotação.', 'error'); return redirect(url_for('dashboard'))
    if request.method == 'POST':
        rating = request.form.get('rating'); comment = request.form.get('comment')
        if not rating: flash('A nota é obrigatória.', 'error'); return redirect(url_for('add_review', quote_id=quote.id))
        new_review = Review(rating=int(rating), comment=comment, quote_id=quote.id, reviewer_id=quote.buyer_id, supplier_id=quote.supplier_id)
        db.session.add(new_review); db.session.commit(); flash('Avaliação enviada com sucesso!', 'success'); return redirect(url_for('dashboard'))
    return render_template('add_review.html', quote=quote)

@app.route('/quote/<int:quote_id>', methods=['GET','POST'])
@login_required
def quote_detail(quote_id):
    quote = db.session.get(QuoteRequest, quote_id)
    if session['company_id'] not in [quote.buyer_id, quote.supplier_id]: flash('Não permitido.', 'error'); return redirect(url_for('dashboard'))
    if request.method == 'POST':
        if session['user_type'] != 'supplier' or session['company_id'] != quote.supplier_id: flash('Ação não permitida.', 'error'); return redirect(url_for('quote_detail', quote_id=quote.id))
        offered_price_str = request.form.get('offered_price'); delivery_date_str = request.form.get('delivery_date')
        if not offered_price_str: flash('O preço da oferta é obrigatório.', 'error'); return redirect(url_for('quote_detail', quote_id=quote.id))
        quote.offered_price=float(offered_price_str); quote.status='Respondido'; quote.response_timestamp=datetime.utcnow()
        if delivery_date_str: quote.delivery_date = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
        notification = Notification(message=f"Cotação para {quote.product.name} foi respondida.", link=url_for('quote_detail', quote_id=quote.id), recipient_id=quote.buyer_id)
        db.session.add(notification); db.session.commit()

        # Emitir notificação em tempo real
        unread_count = db.session.query(Notification).filter_by(recipient_id=quote.buyer_id, read=False).count()
        socketio.emit('new_notification', 
                      {'unread_count': unread_count}, 
                      room=f"user_{quote.buyer_id}")

        buyer_email = quote.buyer.email; supplier_name = quote.supplier.company_name
        email_html = f"<p>Olá, {quote.buyer.company_name},</p><p>Sua solicitação para <strong>{quote.product.name}</strong> foi respondida por <strong>{supplier_name}</strong>.</p><p>Acesse a plataforma para visualizar.</p>"
        send_email("Sua cotação foi respondida!", [buyer_email], email_html)
        flash('Proposta enviada!', 'success'); return redirect(url_for('dashboard'))
    return render_template('quote_detail.html', quote=quote)

@app.route('/quote/<int:quote_id>/accept', methods=['POST'])
@login_required
def accept_quote(quote_id):
    quote = db.session.get(QuoteRequest, quote_id)
    if session.get('user_type') != 'buyer' or session.get('company_id') != quote.buyer_id: flash('Ação não permitida.', 'error'); return redirect(url_for('dashboard'))
    quote.status = 'Aceito'
    notification = Notification(message=f"A proposta para {quote.product.name} foi ACEITA.", link=url_for('quote_detail', quote_id=quote.id), recipient_id=quote.supplier_id)
    db.session.add(notification); db.session.commit()

    # Emitir notificação em tempo real
    unread_count = db.session.query(Notification).filter_by(recipient_id=quote.supplier_id, read=False).count()
    socketio.emit('new_notification', 
                  {'unread_count': unread_count}, 
                  room=f"user_{quote.supplier_id}")
    
    supplier_email = quote.supplier.email; buyer_name = quote.buyer.company_name
    email_html = f"<p>Parabéns, {quote.supplier.company_name}!</p><p>Sua proposta para <strong>{quote.product.name}</strong> foi aceita por <strong>{buyer_name}</strong>.</p>"
    send_email("Sua proposta foi aceita!", [supplier_email], email_html)
    flash('Proposta aceita!', 'success'); return redirect(url_for('dashboard'))

@app.route('/quote/<int:quote_id>/decline', methods=['POST'])
@login_required
def decline_quote(quote_id):
    quote = db.session.get(QuoteRequest, quote_id)
    if session.get('user_type') != 'buyer' or session.get('company_id') != quote.buyer_id: flash('Ação não permitida.', 'error'); return redirect(url_for('dashboard'))
    quote.status = 'Recusado'
    notification = Notification(message=f"A proposta para {quote.product.name} foi recusada.", link=url_for('quote_detail', quote_id=quote.id), recipient_id=quote.supplier_id)
    db.session.add(notification); db.session.commit()

    # Emitir notificação em tempo real
    unread_count = db.session.query(Notification).filter_by(recipient_id=quote.supplier_id, read=False).count()
    socketio.emit('new_notification', 
                  {'unread_count': unread_count}, 
                  room=f"user_{quote.supplier_id}")

    supplier_email = quote.supplier.email; buyer_name = quote.buyer.company_name
    email_html = f"<p>Olá, {quote.supplier.company_name},</p><p>Sua proposta para <strong>{quote.product.name}</strong> foi recusada por <strong>{buyer_name}</strong>.</p>"
    send_email("Sua proposta foi recusada.", [supplier_email], email_html)
    flash('Proposta recusada.', 'info'); return redirect(url_for('dashboard'))

@app.route('/add_product', methods=['GET', 'POST'])
@login_required
@supplier_required
def add_product():
    if request.method == 'POST':
        name=request.form.get('name'); description=request.form.get('description'); category=request.form.get('category'); base_price_str=request.form.get('base_price')
        if not all([name, description, category]): flash('Nome, descrição e categoria são obrigatórios.', 'error'); return redirect(url_for('add_product'))
        base_price = float(base_price_str) if base_price_str else None
        new_product=Product(name=name, description=description, category=category, base_price=base_price, supplier_id=session['company_id'])
        db.session.add(new_product); db.session.flush()
        images = request.files.getlist('product_images')
        for image_file in images:
            if image_file and allowed_file(image_file.filename, ALLOWED_IMG_EXTENSIONS):
                filename=secure_filename(image_file.filename); image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                new_image = ProductImage(filename=filename, product_id=new_product.id)
                db.session.add(new_image)
        db.session.commit(); flash('Produto adicionado com sucesso!', 'success'); return redirect(url_for('dashboard'))
    return render_template('add_product.html')

@app.route('/product/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = db.session.get(Product, product_id)
    if product.supplier_id != session['company_id'] and not session.get('is_admin'):
        flash('Você não tem permissão para editar este produto.', 'error'); return redirect(url_for('dashboard'))
    if request.method == 'POST':
        product.name = request.form.get('name'); product.description = request.form.get('description'); product.category = request.form.get('category'); product.base_price = float(request.form.get('base_price')) if request.form.get('base_price') else None
        images_to_delete = request.form.getlist('delete_images')
        for img_id in images_to_delete:
            image_to_delete = db.session.get(ProductImage, img_id)
            if image_to_delete and image_to_delete.product_id == product.id: db.session.delete(image_to_delete)
        new_images = request.files.getlist('product_images')
        for image_file in new_images:
            if image_file and allowed_file(image_file.filename, ALLOWED_IMG_EXTENSIONS):
                filename=secure_filename(image_file.filename); image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                new_image = ProductImage(filename=filename, product_id=product.id)
                db.session.add(new_image)
        db.session.commit(); flash('Produto atualizado!', 'success')
        if session.get('is_admin'): return redirect(url_for('admin.products'))
        return redirect(url_for('dashboard'))
    return render_template('edit_product.html', product=product)

@app.route('/product/<int:product_id>/delete', methods=['POST'])
@login_required
def delete_product(product_id):
    product = db.session.get(Product, product_id)
    if product.supplier_id != session['company_id'] and not session.get('is_admin'):
        flash('Você não tem permissão para excluir este produto.', 'error'); return redirect(url_for('dashboard'))
    db.session.delete(product); db.session.commit(); flash('Produto excluído!', 'success')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/notifications')
@login_required
def notifications():
    company = db.session.get(Company, session['company_id'])
    for n in company.notifications: n.read = True
    db.session.commit()
    notifications = Notification.query.filter_by(recipient_id=company.id).order_by(Notification.timestamp.desc()).all()
    return render_template('notifications.html', notifications=notifications)

@app.route('/export/quotes')
@login_required
def export_quotes():
    company = db.session.get(Company, session['company_id'])
    quotes_query = company.sent_quotes if company.user_type == 'buyer' else company.received_quotes
    quotes = quotes_query.options(joinedload(QuoteRequest.product), joinedload(QuoteRequest.buyer), joinedload(QuoteRequest.supplier)).all()
    def generate():
        data = StringIO(); writer = csv.writer(data)
        writer.writerow(['ID', 'Produto', 'Status', 'Qtd', 'Preço Ofertado', 'Comprador', 'Fornecedor', 'Data'])
        yield data.getvalue(); data.seek(0); data.truncate(0)
        for quote in quotes:
            writer.writerow([quote.id, quote.product.name, quote.status, quote.quantity, quote.offered_price, quote.buyer.company_name, quote.supplier.company_name, quote.timestamp.strftime('%Y-%m-%d %H:%M:%S')])
            yield data.getvalue(); data.seek(0); data.truncate(0)
    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename="relatorio_cotacoes.csv")
    return response

# --- Blueprint do Admin ---
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
@admin_bp.route('/')
@admin_required
def index():
    stats = { 'total_users': Company.query.count(), 'total_products': Product.query.count(), 'total_quotes': QuoteRequest.query.count() }
    return render_template('admin/index.html', stats=stats)
@admin_bp.route('/chart_data')
@admin_required
def chart_data():
    user_counts = db.session.query(func.strftime('%Y-%m', Company.created_at).label('month'),func.count(Company.id).label('count')).group_by('month').order_by('month').all()
    labels = [row.month for row in user_counts]; data = [row.count for row in user_counts]
    return jsonify({'labels': labels, 'data': data})
@admin_bp.route('/users')
@admin_required
def users():
    all_users = Company.query.order_by(Company.company_name).all()
    return render_template('admin/users.html', users=all_users)
@admin_bp.route('/user/<int:user_id>/toggle_verify', methods=['POST'])
@admin_required
def toggle_verify(user_id):
    user = db.session.get(Company, user_id)
    user.is_verified = not user.is_verified
    db.session.commit(); flash(f"Status de verificação de {user.company_name} alterado.", "success")
    return redirect(url_for('admin.users'))
@admin_bp.route('/user/<int:user_id>/toggle_active', methods=['POST'])
@admin_required
def toggle_active(user_id):
    user = db.session.get(Company, user_id)
    if not user.is_admin:
        user.is_active = not user.is_active
        db.session.commit(); flash(f"Status de atividade de {user.company_name} alterado.", "success")
    else: flash("Não é possível suspender um administrador.", "error")
    return redirect(url_for('admin.users'))
@admin_bp.route('/products')
@admin_required
def products():
    all_products = Product.query.order_by(Product.id.desc()).all()
    return render_template('admin/products.html', products=all_products)
@admin_bp.route('/reviews')
@admin_required
def reviews():
    all_reviews = Review.query.order_by(Review.timestamp.desc()).all()
    return render_template('admin/reviews.html', reviews=all_reviews)
@admin_bp.route('/review/<int:review_id>/delete', methods=['POST'])
@admin_required
def delete_review(review_id):
    review = db.session.get(Review, review_id)
    db.session.delete(review); db.session.commit(); flash('Avaliação removida com sucesso.', 'success')
    return redirect(url_for('admin.reviews'))
@admin_bp.route('/quotes')
@admin_required
def quotes():
    status_filter = request.args.get('status_filter', '')
    query = QuoteRequest.query
    if status_filter: query = query.filter(QuoteRequest.status == status_filter)
    all_quotes = query.order_by(QuoteRequest.timestamp.desc()).all()
    return render_template('admin/quotes.html', quotes=all_quotes, current_filter=status_filter)
@admin_bp.route('/announcements')
@admin_required
def announcements():
    all_announcements = Announcement.query.order_by(Announcement.timestamp.desc()).all()
    return render_template('admin/announcements.html', announcements=all_announcements)
@admin_bp.route('/announcement/new', methods=['GET', 'POST'])
@admin_required
def new_announcement():
    if request.method == 'POST':
        title = request.form.get('title'); content = request.form.get('content')
        if not title or not content: flash('Título e conteúdo são obrigatórios.', 'error'); return redirect(url_for('admin.new_announcement'))
        new_ann = Announcement(title=title, content=content)
        db.session.add(new_ann); db.session.commit(); flash('Anúncio criado com sucesso.', 'success')
        return redirect(url_for('admin.announcements'))
    return render_template('admin/announcement_form.html', form_title="Novo Anúncio")
@admin_bp.route('/announcement/<int:announcement_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_announcement(announcement_id):
    announcement = db.session.get(Announcement, announcement_id)
    if request.method == 'POST':
        announcement.title = request.form.get('title'); announcement.content = request.form.get('content')
        db.session.commit(); flash('Anúncio atualizado com sucesso.', 'success')
        return redirect(url_for('admin.announcements'))
    return render_template('admin/announcement_form.html', form_title="Editar Anúncio", announcement=announcement)
@admin_bp.route('/announcement/<int:announcement_id>/delete', methods=['POST'])
@admin_required
def delete_announcement(announcement_id):
    announcement = db.session.get(Announcement, announcement_id)
    db.session.delete(announcement); db.session.commit(); flash('Anúncio excluído com sucesso.', 'success')
    return redirect(url_for('admin.announcements'))
@admin_bp.route('/announcement/<int:announcement_id>/toggle', methods=['POST'])
@admin_required
def toggle_announcement(announcement_id):
    announcement = db.session.get(Announcement, announcement_id)
    if not announcement.is_active: Announcement.query.update({Announcement.is_active: False})
    announcement.is_active = not announcement.is_active
    db.session.commit(); flash('Status do anúncio alterado com sucesso.', 'success')
    return redirect(url_for('admin.announcements'))
app.register_blueprint(admin_bp)

# --- EVENTOS DO SOCKET.IO PARA O CHAT ---

@socketio.on('connect')
def on_connect():
    """
    Quando um usuário se conecta, se ele estiver logado,
    ele entra em uma "sala" privada com seu ID para notificações.
    """
    if 'company_id' in session:
        room = f"user_{session['company_id']}"
        join_room(room)
        print(f"Cliente {session.get('company_name', 'Desconhecido')} conectado e entrou na sala {room}")

@socketio.on('join')
def on_join(data):
    """Junta-se a uma sala de chat específica da cotação."""
    room = f"quote_{data['quote_id']}"
    join_room(room)

@socketio.on('typing')
def on_typing(data):
    room = f"quote_{data['quote_id']}"
    emit('user_typing', {'sender_name': session['company_name']}, to=room, include_self=False)

@socketio.on('stop_typing')
def on_stop_typing(data):
    room = f"quote_{data['quote_id']}"
    emit('user_stopped_typing', {'sender_name': session['company_name']}, to=room, include_self=False)

@socketio.on('send_message')
def on_send_message(data):
    quote_id = data['quote_id']
    message_text = data.get('message')
    room = f"quote_{quote_id}"
    
    attachment_filename = data.get('attachment')
    attachment_type = None
    if attachment_filename:
        if '.' in attachment_filename:
            ext = attachment_filename.rsplit('.', 1)[1].lower()
            if ext in {'png', 'jpg', 'jpeg', 'gif'}:
                attachment_type = 'image'
            else:
                attachment_type = 'file'

    if not message_text and not attachment_filename:
        return # Não envia mensagem vazia

    new_message = ChatMessage(
        message=message_text,
        quote_id=quote_id,
        sender_id=session['company_id'],
        attachment_filename=attachment_filename,
        attachment_type=attachment_type
    )
    db.session.add(new_message)
    db.session.commit()

    message_payload = {
        'message': new_message.message,
        'sender_name': new_message.sender.company_name,
        'timestamp': new_message.timestamp.strftime('%d/%m/%Y %H:%M'),
        'attachment_filename': new_message.attachment_filename,
        'attachment_type': new_message.attachment_type
    }
    send(message_payload, to=room)

@app.route('/chat/upload', methods=['POST'])
@login_required
def upload_chat_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nome de arquivo vazio'}), 400
    if file and allowed_file(file.filename, ALLOWED_ATTACH_EXTENSIONS):
        filename = secure_filename(f"{datetime.utcnow().timestamp()}_{file.filename}")
        file.save(os.path.join(app.config['CHAT_ATTACHMENT_FOLDER'], filename))
        return jsonify({'filename': filename})
    return jsonify({'error': 'Tipo de arquivo não permitido'}), 400

# --- Execução da Aplicação ---
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)