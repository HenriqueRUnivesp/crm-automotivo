import os
import re

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user
from werkzeug.security import check_password_hash

from database import Historico, Lead, Usuario, Veiculo, db, inicializar_banco


app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


@login_manager.user_loader
def carregar_usuario(usuario_id):
    return db.session.get(Usuario, int(usuario_id))


def normalizar_telefone(telefone):
    telefone_limpo = re.sub(r"\D", "", str(telefone or ""))
    if telefone_limpo and not telefone_limpo.startswith("55"):
        telefone_limpo = f"55{telefone_limpo}"
    return telefone_limpo


def buscar_veiculo_interesse(valor):
    if not valor:
        return None

    if isinstance(valor, int) or str(valor).isdigit():
        veiculo = db.session.get(Veiculo, int(valor))
        if veiculo:
            return veiculo

    return Veiculo.query.filter(
        (Veiculo.modelo.ilike(f"%{valor}%")) | (Veiculo.placa.ilike(str(valor)))
    ).first()


def registrar_historico(lead, descricao):
    historico = Historico(descricao=descricao, lead=lead)
    db.session.add(historico)
    return historico


def criar_lead(nome, telefone, origem, veiculo_interesse=None):
    veiculo_interesse = (veiculo_interesse or "").strip() or None
    veiculo = buscar_veiculo_interesse(veiculo_interesse)
    lead = Lead(
        nome=nome,
        telefone=normalizar_telefone(telefone),
        origem=origem,
        status_funil="Novo",
        veiculo_interesse=veiculo_interesse,
        veiculo=veiculo,
    )
    db.session.add(lead)
    db.session.flush()

    descricao = f"Lead criado via {origem}."
    if veiculo_interesse:
        descricao = f"{descricao} Veiculo de interesse: {veiculo_interesse}."
    registrar_historico(lead, descricao)

    db.session.commit()
    return lead


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        dados = request.get_json(silent=True) or {}
        usuario_form = request.form.get("usuario") or dados.get("usuario")
        senha_form = request.form.get("senha") or dados.get("senha")
        usuario = Usuario.query.filter_by(usuario=usuario_form).first()

        if usuario and check_password_hash(usuario.senha_hash, senha_form or ""):
            login_user(usuario)
            return redirect(url_for("index"))

        if request.is_json:
            return jsonify({"erro": "Usuario ou senha invalidos."}), 401
        return render_template("login.html", erro="Usuario ou senha invalidos."), 401

    return render_template("login.html")


@app.route("/")
@login_required
def index():
    leads = Lead.query.order_by(Lead.data_criacao.desc()).all()
    return render_template("index.html", leads=leads)


@app.route("/cadastrar_lead", methods=["GET", "POST"])
@login_required
def cadastrar_lead():
    if request.method == "POST":
        nome = request.form.get("nome")
        telefone = request.form.get("telefone")
        origem = request.form.get("origem") or "Manual"
        veiculo_interesse = request.form.get("veiculo_interesse")

        if not nome or not telefone:
            return render_template(
                "cadastrar_lead.html",
                erro="Nome e telefone sao obrigatorios.",
                dados=request.form,
            ), 400

        criar_lead(nome, telefone, origem, veiculo_interesse)
        return redirect(url_for("index"))

    return render_template("cadastrar_lead.html")


@app.route("/editar_lead/<int:lead_id>", methods=["GET", "POST"])
@login_required
def editar_lead(lead_id):
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return redirect(url_for("index"))

    if request.method == "POST":
        nome = request.form.get("nome")
        telefone = request.form.get("telefone")
        origem = request.form.get("origem") or "Manual"
        veiculo_interesse = (request.form.get("veiculo_interesse") or "").strip() or None
        status_funil = request.form.get("status_funil") or lead.status_funil

        if not nome or not telefone:
            return render_template(
                "editar_lead.html",
                lead=lead,
                erro="Nome e telefone sao obrigatorios.",
            ), 400

        lead.nome = nome
        lead.telefone = normalizar_telefone(telefone)
        lead.origem = origem
        lead.status_funil = status_funil
        lead.veiculo_interesse = veiculo_interesse
        lead.veiculo = buscar_veiculo_interesse(veiculo_interesse)
        registrar_historico(lead, "Dados do lead atualizados manualmente.")
        db.session.commit()

        return redirect(url_for("index"))

    return render_template("editar_lead.html", lead=lead)


@app.route("/anotacoes/<int:lead_id>", methods=["GET", "POST"])
@login_required
def anotacoes_lead(lead_id):
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return redirect(url_for("index"))

    if request.method == "POST":
        descricao = (request.form.get("descricao") or "").strip()
        if descricao:
            registrar_historico(lead, descricao)
            db.session.commit()
        return redirect(url_for("anotacoes_lead", lead_id=lead.id))

    historicos = Historico.query.filter_by(lead_id=lead.id).order_by(Historico.data_registro.desc()).all()
    return render_template("anotacoes_lead.html", lead=lead, historicos=historicos)


@app.route("/excluir_lead/<int:lead_id>", methods=["POST"])
@login_required
def excluir_lead(lead_id):
    lead = db.session.get(Lead, lead_id)
    if lead:
        db.session.delete(lead)
        db.session.commit()
    return redirect(url_for("index"))


@app.route("/webhook/webmotors", methods=["POST"])
def webhook_webmotors():
    if request.args.get("token") != "ChaveSecretaCRM":
        return jsonify({"erro": "Token invalido."}), 403

    dados = request.get_json(silent=True) or {}
    nome = dados.get("nome") or dados.get("cliente") or dados.get("name")
    telefone = dados.get("telefone") or dados.get("phone")
    veiculo_interesse = (
        dados.get("veiculo_interesse")
        or dados.get("veiculo")
        or dados.get("modelo")
        or dados.get("vehicle")
    )

    if not nome or not telefone:
        return jsonify({"erro": "Nome e telefone sao obrigatorios."}), 400

    lead = criar_lead(nome, telefone, "Webmotors", veiculo_interesse)
    return jsonify({"mensagem": "Lead cadastrado com sucesso.", "lead_id": lead.id}), 201


@app.route("/webhook/mercadolivre", methods=["POST"])
def webhook_mercadolivre():
    dados = request.get_json(silent=True) or {}
    comprador = {}

    url_comprador = dados.get("buyer_url") or dados.get("comprador_url") or dados.get("resource")
    if url_comprador:
        resposta = requests.get(url_comprador, timeout=10)
        if resposta.ok:
            comprador = resposta.json()

    nome = comprador.get("nome") or comprador.get("name") or dados.get("nome") or "Comprador Mercado Livre"
    telefone = (
        comprador.get("telefone")
        or comprador.get("phone")
        or comprador.get("phone_number")
        or dados.get("telefone")
        or "5500000000000"
    )
    veiculo_interesse = dados.get("veiculo_interesse") or dados.get("veiculo") or dados.get("item_id")

    lead = criar_lead(nome, telefone, "Mercado Livre", veiculo_interesse)
    return jsonify({"mensagem": "Lead do Mercado Livre cadastrado.", "lead_id": lead.id}), 201


@app.route("/mudar_status/<int:lead_id>", methods=["POST"])
@login_required
def mudar_status(lead_id):
    lead = db.session.get(Lead, lead_id)
    if not lead:
        return jsonify({"erro": "Lead nao encontrado."}), 404

    dados = request.get_json(silent=True) or request.form
    novo_status = dados.get("status") or dados.get("status_funil")
    if not novo_status:
        return jsonify({"erro": "Novo status e obrigatorio."}), 400

    status_anterior = lead.status_funil
    lead.status_funil = novo_status
    registrar_historico(lead, f"Status alterado de '{status_anterior}' para '{novo_status}'.")
    db.session.commit()

    if not request.is_json:
        return redirect(url_for("index"))

    return jsonify(
        {
            "mensagem": "Status atualizado com sucesso.",
            "lead_id": lead.id,
            "status_funil": lead.status_funil,
        }
    )


inicializar_banco(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
