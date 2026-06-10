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
 
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_NUM = "whatsapp:+14155238886"
GOOGLE_SHEET_NAME   = "Trading Journal 2026"
 
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
 
SYSTEM_PROMPT = """Eres un asistente de trading journal.
Analiza el mensaje o imagen y devuelve SOLO un JSON valido sin markdown ni texto extra:
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
Fecha de hoy si no se especifica: """ + datetime.now().strftime("%Y-%m-%d")
 
 
def parse_trade_message(body, image_url=None):
    if image_url:
        content = [
            {"type": "image", "source": {"type": "url", "url": image_url}},
            {"type": "text", "text": f"Analiza este screenshot de TradingView y extrae los datos del trade. Comentario del trader: {body or 'Sin comentario'}"}
        ]
    else:
        content = body
 
    response = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}]
    )
 
    raw = response.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)
 
 
def save_to_sheets(trade, raw_message):
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_dict = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("DIARIO")
 
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
            now.strftime("%W"),
            now.month,
            now.year,
            raw_message
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        print(f"Error Sheets: {e}")
        return False
 
 
def build_response(trade):
    plan = "✔️ Respetado" if trade.get("respeto_plan") else "❌ No respetado"
    pct = trade.get("porcentaje", 0)
    usd = trade.get("resultado_usd", 0)
    emoji = "📈" if pct >= 0 else "📉"
    sign_pct = "+" if pct >= 0 else ""
    sign_usd = "$+" if usd >= 0 else "$"
 
    return f"""{emoji} *Registrado — {datetime.now().strftime("%d %b %Y")}*
 
*{sign_pct}{pct}%* | {trade.get("num_trades", 0)} trades | {trade.get("par", "N/D")} | *{sign_usd}{usd}*
🧠 {trade.get("emocion", "")}
📋 Plan: {plan}
 
_Guardado en tu Trading Journal_ ✅"""
 
 
def handle_summary(phone):
    try:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_dict = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet("DIARIO")
 
        records = sheet.get_all_records()
        week = datetime.now().strftime("%W")
        weekly = [r for r in records if str(r.get("semana_num", "")) == week]
 
        if not weekly:
            msg = "📊 No hay registros esta semana aún."
        else:
            pcts = [float(r["porcentaje"]) for r in weekly if r.get("porcentaje")]
            usds = [float(r["resultado_usd"]) for r in weekly if r.get("resultado_usd")]
            plans = [r for r in weekly if r.get("respeto_plan") is True or r.get("respeto_plan") == "TRUE"]
            total_pct = round(sum(pcts), 2)
            total_usd = round(sum(usds), 2)
            sign = "+" if total_pct >= 0 else ""
            msg = f"""📊 *Resumen Semana {week}*\n\n📈 Rendimiento: *{sign}{total_pct}%*\n💵 Total USD: *${total_usd}*\n📅 Días operados: {len(weekly)}\n✔️ Plan respetado: {len(plans)}/{len(weekly)} días\n🏆 Mejor día: +{max(pcts)}%\n📉 Peor día: {min(pcts)}%"""
 
        send_whatsapp(phone, msg)
    except Exception as e:
        send_whatsapp(phone, f"❌ Error generando resumen: {str(e)[:100]}")
 
 
def send_whatsapp(to, message):
    twilio.messages.create(from_=TWILIO_WHATSAPP_NUM, to=to, body=message)
 
 
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.form.get("Body", "").strip()
    from_num = request.form.get("From", "")
    image_url = request.form.get("MediaUrl0")
 
    try:
        if body.lower() in ["resumen semana", "resumen", "summary"]:
            handle_summary(from_num)
            return str(MessagingResponse())
 
        if body.lower() in ["ayuda", "help", "comandos"]:
            send_whatsapp(from_num, "🤖 *Trading Journal Bot*\n\n• Envía un mensaje con tu trade\n• Envía una foto de TradingView\n• `resumen semana` — resumen semanal\n• `ayuda` — este menú\n\n*Ejemplo:*\n_Hoy +1.2%, 2 trades, EUR/USD, +$600, respete el plan_")
            return str(MessagingResponse())
 
        if not body and not image_url:
            send_whatsapp(from_num, "⚠️ Envía un texto con tu trade o una foto de TradingView.")
            return str(MessagingResponse())
 
        trade = parse_trade_message(body, image_url)
        if image_url:
            trade["screenshot_url"] = image_url
 
        saved = save_to_sheets(trade, body)
        response_msg = build_response(trade)
        if not saved:
            response_msg += "\n\n⚠️ _Error al guardar en Sheets_"
 
        send_whatsapp(from_num, response_msg)
 
    except json.JSONDecodeError:
        send_whatsapp(from_num, "⚠️ No pude interpretar el trade. Intenta: +1.2%, 2 trades, EUR/USD, +$600")
    except Exception as e:
        send_whatsapp(from_num, f"❌ Error: {str(e)[:100]}")
 
    return str(MessagingResponse())
 
 
@app.route("/", methods=["GET"])
def health():
    return "Trading Journal Bot activo ✅", 200
 
 
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
