import os
from dotenv import load_dotenv

# Define o caminho base do projeto
basedir = os.path.abspath(os.path.dirname(__file__))

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    """
    Define as configurações da aplicação, carregando dados sensíveis
    do ambiente e fornecendo valores padrão para os não sensíveis.
    """
    # Chave secreta da aplicação
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'uma-chave-padrao-caso-nao-seja-definida'

    # Configuração do Banco de Dados
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'connecta.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Configuração de Uploads
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    ATTACHMENT_FOLDER = os.path.join(basedir, 'static', 'attachments')
    CHAT_ATTACHMENT_FOLDER = os.path.join(basedir, 'static', 'chat_attachments') # ADICIONADO

    # Configuração de E-mail (LÊ DO ARQUIVO .env)
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS') is not None
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = ('Connecta B2B', MAIL_USERNAME)
    
    # ADICIONADO: Configuração do Celery
    # (Presume que o Redis (broker) está rodando localmente na porta padrão)
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://localhost:6379/0'
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or 'redis://localhost:6379/0'