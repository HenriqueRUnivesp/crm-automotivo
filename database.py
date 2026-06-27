import os
from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash


db = SQLAlchemy()


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    usuario = db.Column(db.String(80), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(255), nullable=False)
    cargo = db.Column(db.String(80), nullable=False)


class Veiculo(db.Model):
    __tablename__ = "veiculos"

    id = db.Column(db.Integer, primary_key=True)
    modelo = db.Column(db.String(120), nullable=False)
    placa = db.Column(db.String(20), unique=True, nullable=False, index=True)
    preco = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), nullable=False, default="Disponível")

    leads = db.relationship("Lead", back_populates="veiculo")


class Lead(db.Model):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    telefone = db.Column(db.String(30), nullable=False)
    origem = db.Column(db.String(80), nullable=False)
    status_funil = db.Column(db.String(50), nullable=False, default="Novo")
    data_criacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    veiculo_interesse = db.Column(db.String(160), nullable=True)
    veiculo_id = db.Column(db.Integer, db.ForeignKey("veiculos.id"), nullable=True)

    veiculo = db.relationship("Veiculo", back_populates="leads")
    historicos = db.relationship("Historico", back_populates="lead", cascade="all, delete-orphan")


class Historico(db.Model):
    __tablename__ = "historicos"

    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.Text, nullable=False)
    data_registro = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False)

    lead = db.relationship("Lead", back_populates="historicos")


def _garantir_colunas_leads():
    colunas = {coluna["name"] for coluna in inspect(db.engine).get_columns("leads")}
    if "veiculo_interesse" not in colunas:
        db.session.execute(text("ALTER TABLE leads ADD COLUMN veiculo_interesse VARCHAR(160)"))
        db.session.commit()


def _preencher_veiculos_antigos():
    historicos = Historico.query.filter(Historico.descricao.like("%Veiculo de interesse:%")).all()
    for historico in historicos:
        lead = historico.lead
        if lead and not lead.veiculo_interesse:
            lead.veiculo_interesse = historico.descricao.split("Veiculo de interesse:", 1)[1].strip().rstrip(".")
    db.session.commit()


def inicializar_banco(app):
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///crm.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _garantir_colunas_leads()
        _preencher_veiculos_antigos()

        admin = Usuario.query.filter_by(usuario="admin").first()
        if not admin:
            admin = Usuario(
                nome="Administrador",
                usuario="admin",
                senha_hash=generate_password_hash("Admin123@"),
                cargo="Administrador",
            )
            db.session.add(admin)
            db.session.commit()
