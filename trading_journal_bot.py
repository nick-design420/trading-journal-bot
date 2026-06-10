"""
Trading Journal Bot — WhatsApp + Claude Vision + Google Sheets
Deploy en Railway.app en 5 minutos
"""

from flask import Flask, request
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import os

app = Flask(__name__)

# ─────────────────────────────────────────
# CONFIGURACIÓN — Solo cambia estos valores
# ─────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-...")
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID", "ACxxxxxxx")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "xxxxxxx")
TWILIO_WHATSAPP_NUM = "whatsapp:+14155238886"
GOOGLE_SHEET_NAME   = "Trading Journal 2026"
# ─────────────────────────────────────────

claude  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
twilio  = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

SYSTEM_PROMPT = """Eres un asistente de trading journal. 
Analiza el mensaje o imagen y devuelve SOLO un JSON válido sin markdown ni texto extra:
{
  "fecha": "YYYY-MM-DD",
  "porcentaje": numero con signo,
  "num_trades": numero entero,
  "par": "string ej: EUR/USD",
  "resultado_usd": numero con signo,
  "respeto_plan": true o false,
  "emocion": "string corto",
  "comentario": "string",
  "screenshot_url": null
}
Si es una imagen de TradingView, extrae los datos del gráfico.
Si falta información, usa valores razonables basados en el contexto.
Fecha de hoy si no se especifica: """ + datetime.now().strftime("%Y-%m-%d")


def parse_trade_message(body: str, image_url: str = None) -> dict:
    """Llama a Claude para parsear el mensaje o imagen del trader."""
    
    if image_url:
        # Modo imagen — Claude Vision analiza el screenshot de TradingView
        content = [
            {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": image_url
                }
            },
            {
                "type": "text",
                "text": f"Analiza este screenshot de TradingView y extrae los datos del trade. Comentario del trader: {body or 'Sin comentario'}"
            }
        ]
    else:
        # Modo texto — parsea el mensaje
        content = body

    response = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}]
    )
    
    raw = response.content[0].text.strip()
    # Limpiar markdown si Claude lo incluye
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def save_to_sheets(trade: dict, raw_message: str):
    """Guarda el trade en Google Sheets."""
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds  = Credentials.from_service_account_file("credentials.json", scopes=scope)
        client = gspread.authorize(creds)
        sheet  = client.open(GOOGLE_SHEET_NAME).worksheet("DIARIO")
        
        now = datetime.now()
        row = [
            trade.get("fecha", now.strftime("%Y-%m-%d")),
            now.strftime("%A"),
            trade.get("porcentaje", 0),
            trade.get("num_trades", 0),
            trade.get("par", "N/D"),
            trade.get("resultado_usd", 0),
            trade.get("respeto_plan", False),
            trade.get("emocion", ""),
            trade.get("comentario", ""),
            trade.get("screenshot_url", ""),
            now.strftime("%W"),   # semana
            now.strftime("%-m"),  # mes
            now.strftime("%Y"),   # año
            raw_message
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        print(f"Error Sheets: {e}")
        return False


def build_response(trade: dict) -> str:
    """Genera el mensaje de respuesta para WhatsApp."""
    plan = "✔️ Respetado" if trade.get("respeto_plan") else "❌ No respetado"
    pct  = trade.get("porcentaje", 0)
    usd  = trade.get("resultado_usd", 0)
    emoji = "📈" if pct >= 0 else "📉"
    
    return f"""{emoji} *Registrado — {datetime.now().strftime("%d %b %Y")}*

*{'+' if pct >= 0 else ''}{pct}%* | {trade.get('num_trades', 0)} trades | {trade.get('par', 'N/D')} | *{'$+' if usd >= 0 else '$'}{usd}*
🧠 {trade.get('emocion', '')}
📋 Plan: {plan}

_Guardado en tu Trading Journal_ ✅"""


def handle_summary(phone: str):
    """Genera resumen semanal desde Google Sheets."""
    try:
        scope  = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_file("credentials.json", scopes=scope)
        client = gspread.authorize(creds)
        sheet  = client.open(GOOGLE_SHEET_NAME).worksheet("DIARIO")
        
        records = sheet.get_all_records()
        week = datetime.now().strftime("%W")
        month = datetime.now().strftime("%-m")
        
        weekly = [r for r in records if str(r.get("semana_num", "")) == week]
        monthly = [r for r in records if str(r.get("mes", "")) == month]
        
        if not weekly:
            msg = "📊 No hay registros esta semana aún."
        else:
            pcts  = [float(r["porcentaje"]) for r in weekly if r["porcentaje"]]
            usds  = [float(r["resultado_usd"]) for r in weekly if r["resultado_usd"]]
            plans = [r for r in weekly if r["respeto_plan"] is True or r["respeto_plan"] == "TRUE"]
            
            msg = f"""📊 *Resumen Semana {week}*

📈 Rendimiento: *{'+' if sum(pcts) >= 0 else ''}{round(sum(pcts), 2)}%*
💵 Total USD: *{'$+' if sum(usds) >= 0 else '$'}{round(sum(usds), 2)}*
📅 Días operados: {len(weekly)}
✔️ Plan respetado: {len(plans)}/{len(weekly)} días
🏆 Mejor día: +{max(pcts)}%
📉 Peor día: {min(pcts)}%

📆 *Mes actual:* {len(monthly)} registros"""

        send_whatsapp(phone, msg)
    except Exception as e:
        send_whatsapp(phone, f"❌ Error generando resumen: {e}")


def send_whatsapp(to: str, message: str):
    """Envía mensaje de WhatsApp vía Twilio."""
    twilio.messages.create(
        from_=TWILIO_WHATSAPP_NUM,
        to=to,
        body=message
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    """Endpoint principal — recibe mensajes de Twilio."""
    body      = request.form.get("Body", "").strip()
    from_num  = request.form.get("From", "")
    image_url = request.form.get("MediaUrl0")  # imagen adjunta
    
    try:
        # Comandos especiales
        if body.lower() in ["resumen semana", "resumen", "summary"]:
            handle_summary(from_num)
            return str(MessagingResponse())
        
        if body.lower() in ["ayuda", "help", "comandos"]:
            send_whatsapp(from_num, """🤖 *Trading Journal Bot*

*Comandos disponibles:*
• Envía un mensaje con tu trade
• Envía una foto de TradingView
• `resumen semana` — ver resumen semanal
• `ayuda` — este menú

*Ejemplo de mensaje:*
_Hoy +1.2%, 2 trades, EUR/USD, +$600, respeté el plan, buena ejecución_""")
            return str(MessagingResponse())
        
        # Sin contenido
        if not body and not image_url:
            send_whatsapp(from_num, "⚠️ No entendí el mensaje. Envía un texto con tu trade o una foto de TradingView.")
            return str(MessagingResponse())
        
        # Parsear trade con Claude
        trade = parse_trade_message(body, image_url)
        if image_url:
            trade["screenshot_url"] = image_url
        
        # Guardar en Google Sheets
        saved = save_to_sheets(trade, body)
        
        # Responder por WhatsApp
        response_msg = build_response(trade)
        if not saved:
            response_msg += "\n\n⚠️ _Error al guardar en Sheets_"
        
        send_whatsapp(from_num, response_msg)
        
    except json.JSONDecodeError:
        send_whatsapp(from_num, "⚠️ No pude interpretar el trade. Intenta con más detalle:\n_Ej: +1.2%, 2 trades, EUR/USD, +$600_")
    except Exception as e:
        send_whatsapp(from_num, f"❌ Error inesperado: {str(e)[:100]}")
    
    return str(MessagingResponse())


@app.route("/", methods=["GET"])
def health():
    return "Trading Journal Bot activo ✅", 200


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5000)))
