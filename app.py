# -*- coding: utf-8 -*-

import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime

# --- Configuração da Aplicação ---
basedir = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-segura-e-dificil-de-adivinhar'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'connecta.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db = SQLAlchemy(app)

# --- Funções Auxiliares e Decoradores (sem alterações) ---

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'company_id' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def supplier_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_type') != 'supplier':
            flash('Acesso negado. Esta área é restrita para fornecedores.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# --- Modelos do Banco de Dados ---

class Company(db.Model):
    # (sem alterações no modelo Company)
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    cnpj = db.Column(db.String(18), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    user_type = db.Column(db.String(50), nullable=False)
    products = db.relationship('Product', backref='supplier', lazy=True)
    sent_quotes = db.relationship('QuoteRequest', foreign_keys='QuoteRequest.buyer_id', backref='buyer', lazy='dynamic')
    received_quotes = db.relationship('QuoteRequest', foreign_keys='QuoteRequest.supplier_id', backref='quote_supplier', lazy='dynamic')

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Product(db.Model):
    # (sem alterações no modelo Product)
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    base_price = db.Column(db.Float, nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    quote_requests = db.relationship('QuoteRequest', backref='product', lazy=True)

# MODELO ATUALIZADO: SOLICITAÇÃO DE COTAÇÃO
class QuoteRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quantity = db.Column(db.Integer, nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='Pendente')
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    buyer_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)

    # NOVOS CAMPOS PARA A RESPOSTA DO FORNECEDOR
    offered_price = db.Column(db.Float, nullable=True) # Preço total ou unitário ofertado
    supplier_message = db.Column(db.Text, nullable=True)
    response_timestamp = db.Column(db.DateTime, nullable=True)


# --- Rotas da Aplicação ---

# (Rotas de home, register, login, logout, products, add_product permanecem inalteradas)
@app.route('/')
def home(): return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # (código inalterado)
        company_name = request.form.get('company_name'); cnpj = request.form.get('cnpj'); email = request.form.get('email'); password = request.form.get('password'); user_type = request.form.get('user_type')
        if not all([company_name, cnpj, email, password, user_type]): flash('Todos os campos são obrigatórios.', 'error'); return redirect(url_for('register'))
        if Company.query.filter_by(email=email).first(): flash('Este e-mail já está cadastrado.', 'error'); return redirect(url_for('register'))
        if Company.query.filter_by(cnpj=cnpj).first(): flash('Este CNPJ já está cadastrado.', 'error'); return redirect(url_for('register'))
        new_company = Company(company_name=company_name, cnpj=cnpj, email=email, user_type=user_type)
        new_company.set_password(password)
        db.session.add(new_company); db.session.commit()
        flash('Empresa cadastrada com sucesso! Por favor, faça o login.', 'success'); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # (código inalterado)
        email = request.form.get('email'); password = request.form.get('password')
        if not email or not password: flash('E-mail e senha são obrigatórios.', 'error'); return redirect(url_for('login'))
        company = Company.query.filter_by(email=email).first()
        if company and company.check_password(password):
            session['company_id'] = company.id; session['company_name'] = company.company_name; session['user_type'] = company.user_type
            flash(f'Login realizado com sucesso! Bem-vindo, {company.company_name}.', 'success'); return redirect(url_for('dashboard'))
        else: flash('E-mail ou senha inválidos.', 'error'); return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear(); flash('Você saiu da sua conta com sucesso.', 'success'); return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard():
    company = Company.query.get(session['company_id'])
    if company.user_type == 'supplier':
        my_products = company.products
        quotes = company.received_quotes.order_by(QuoteRequest.timestamp.desc()).all()
        return render_template('dashboard.html', products=my_products, quotes=quotes)
    else: # Buyer
        quotes = company.sent_quotes.order_by(QuoteRequest.timestamp.desc()).all()
        return render_template('dashboard.html', quotes=quotes)

@app.route('/products')
@login_required
def products():
    all_products = Product.query.order_by(Product.id.desc()).all()
    return render_template('products.html', products=all_products)

@app.route('/product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        # (código inalterado)
        if session['user_type'] != 'buyer': flash('Apenas compradores podem solicitar cotações.', 'error'); return redirect(url_for('product_detail', product_id=product.id))
        quantity = request.form.get('quantity'); message = request.form.get('message')
        if not quantity or not quantity.isdigit() or int(quantity) <= 0: flash('Por favor, insira uma quantidade válida.', 'error'); return redirect(url_for('product_detail', product_id=product.id))
        new_quote = QuoteRequest(quantity=int(quantity), message=message, product_id=product.id, buyer_id=session['company_id'], supplier_id=product.supplier_id)
        db.session.add(new_quote); db.session.commit()
        flash('Solicitação de cotação enviada com sucesso!', 'success'); return redirect(url_for('dashboard'))
    return render_template('product_detail.html', product=product)

@app.route('/add_product', methods=['GET', 'POST'])
@login_required
@supplier_required
def add_product():
    if request.method == 'POST':
        # (código inalterado)
        name = request.form.get('name'); description = request.form.get('description'); category = request.form.get('category'); base_price_str = request.form.get('base_price'); image_file = request.files.get('product_image')
        if not all([name, description, category]): flash('Nome, descrição e categoria são obrigatórios.', 'error'); return redirect(url_for('add_product'))
        filename = None
        if image_file and allowed_file(image_file.filename):
            filename = secure_filename(image_file.filename); image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        base_price = float(base_price_str) if base_price_str else None
        new_product = Product(name=name, description=description, category=category, base_price=base_price, supplier_id=session['company_id'], image_filename=filename)
        db.session.add(new_product); db.session.commit()
        flash('Produto adicionado com sucesso!', 'success'); return redirect(url_for('dashboard'))
    return render_template('add_product.html')

# NOVA ROTA: DETALHES DA COTAÇÃO E RESPOSTA DO FORNECEDOR
@app.route('/quote/<int:quote_id>', methods=['GET', 'POST'])
@login_required
def quote_detail(quote_id):
    quote = QuoteRequest.query.get_or_404(quote_id)
    
    # Segurança: Apenas o comprador que criou ou o fornecedor que recebeu podem ver
    if session['company_id'] not in [quote.buyer_id, quote.supplier_id]:
        flash('Você не tem permissão para visualizar esta cotação.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Apenas o fornecedor pode responder
        if session['user_type'] != 'supplier' or session['company_id'] != quote.supplier_id:
            flash('Ação não permitida.', 'error')
            return redirect(url_for('quote_detail', quote_id=quote.id))

        offered_price_str = request.form.get('offered_price')
        supplier_message = request.form.get('supplier_message')

        if not offered_price_str:
            flash('O preço da oferta é obrigatório.', 'error')
            return redirect(url_for('quote_detail', quote_id=quote.id))

        # Atualiza a cotação com a resposta
        quote.offered_price = float(offered_price_str)
        quote.supplier_message = supplier_message
        quote.status = 'Respondido'
        quote.response_timestamp = datetime.utcnow()
        
        db.session.commit()
        flash('Proposta enviada com sucesso!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('quote_detail.html', quote=quote)


# --- Execução ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)