from flask import Flask, render_template, request
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import unicodedata
import requests
from urllib.parse import quote

app = Flask(__name__)

CARPETA = os.path.dirname(os.path.abspath(__file__))

ARCHIVO_BASE = os.path.join(CARPETA, "BASE DE DATOS CALIDAD Y TÉCNICO.csv")
ARCHIVO_CHARLAS = os.path.join(CARPETA, "CHARLAS.csv")
ARCHIVO_ASISTENCIA_LOCAL = os.path.join(CARPETA, "REGISTRO_ASISTENCIA.csv")

ZONA_HORARIA = ZoneInfo("America/Guayaquil")

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Asistencias")


def ahora_ecuador():
    return datetime.now(ZONA_HORARIA)


def normalizar_texto(texto):
    texto = str(texto).strip().upper()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def leer_csv_seguro(ruta):
    try:
        return pd.read_csv(ruta, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(ruta, dtype=str, encoding="latin1")


def cargar_base_datos():
    if not os.path.exists(ARCHIVO_BASE):
        raise FileNotFoundError(f"No se encontró el archivo base: {ARCHIVO_BASE}")

    df = leer_csv_seguro(ARCHIVO_BASE)
    df.columns = df.columns.str.strip()
    return df


def cargar_charlas():
    if not os.path.exists(ARCHIVO_CHARLAS):
        return None, f"No se encontró el archivo de charlas: {ARCHIVO_CHARLAS}"

    df = leer_csv_seguro(ARCHIVO_CHARLAS)
    df.columns = df.columns.str.strip()

    columnas_requeridas = ["Fecha", "Area", "Charla"]

    for columna in columnas_requeridas:
        if columna not in df.columns:
            return None, f"No se encontró la columna '{columna}' en CHARLAS.csv."

    return df, None


def buscar_persona(cedula):
    try:
        df = cargar_base_datos()
    except Exception as e:
        return None, None, f"Error al cargar la base de datos: {e}"

    col_cedula = "CEDULA DE IDENTIDAD"
    col_nombre = "NOMBRES"
    col_area = "Area"

    if col_cedula not in df.columns:
        return None, None, f"No se encontró la columna: {col_cedula}"

    if col_nombre not in df.columns:
        return None, None, f"No se encontró la columna: {col_nombre}"

    if col_area not in df.columns:
        return None, None, f"No se encontró la columna: {col_area}"

    df[col_cedula] = df[col_cedula].astype(str).str.strip()
    cedula = str(cedula).strip()

    resultado = df[df[col_cedula] == cedula]

    if resultado.empty:
        return None, None, "Cédula no encontrada en la base de datos."

    nombre = str(resultado.iloc[0][col_nombre]).strip()
    area = str(resultado.iloc[0][col_area]).strip()

    return nombre, area, None


def buscar_charla_del_dia_por_area(area_persona):
    df, error = cargar_charlas()

    if error:
        return None, error

    fecha_actual = ahora_ecuador().strftime("%Y-%m-%d")

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["Area_Normalizada"] = df["Area"].apply(normalizar_texto)

    area_persona_normalizada = normalizar_texto(area_persona)

    resultado = df[
        (df["Fecha"] == fecha_actual) &
        (df["Area_Normalizada"] == area_persona_normalizada)
    ]

    if resultado.empty:
        return "Sin charla asignada para esta área", None

    charla = str(resultado.iloc[0]["Charla"]).strip()

    return charla, None


def registrar_asistencia_airtable(cedula, nombre, area, charla, fecha, hora):
    if not AIRTABLE_TOKEN:
        raise ValueError("No se encontró AIRTABLE_TOKEN en Render.")

    if not AIRTABLE_BASE_ID:
        raise ValueError("No se encontró AIRTABLE_BASE_ID en Render.")

    tabla_codificada = quote(AIRTABLE_TABLE_NAME)
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{tabla_codificada}"

    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "records": [
            {
                "fields": {
                    "Cedula": str(cedula),
                    "Nombre": str(nombre),
                    "Area": str(area),
                    "Charla": str(charla),
                    "Fecha": str(fecha),
                    "Hora": str(hora)
                }
            }
        ],
        "typecast": True
    }

    respuesta = requests.post(url, headers=headers, json=data, timeout=20)

    if respuesta.status_code not in [200, 201]:
        raise Exception(f"Error de Airtable: {respuesta.status_code} - {respuesta.text}")


def registrar_asistencia_local_respaldo(cedula, nombre, area, charla, fecha, hora):
    nuevo_registro = pd.DataFrame([{
        "Cedula": cedula,
        "Nombre": nombre,
        "Area": area,
        "Charla": charla,
        "Fecha": fecha,
        "Hora": hora
    }])

    if os.path.exists(ARCHIVO_ASISTENCIA_LOCAL):
        asistencia = leer_csv_seguro(ARCHIVO_ASISTENCIA_LOCAL)
        asistencia = pd.concat([asistencia, nuevo_registro], ignore_index=True)
    else:
        asistencia = nuevo_registro

    asistencia.to_csv(ARCHIVO_ASISTENCIA_LOCAL, index=False, encoding="utf-8-sig")


def registrar_asistencia(cedula, nombre, area, charla):
    ahora = ahora_ecuador()
    fecha = ahora.strftime("%Y-%m-%d")
    hora = ahora.strftime("%H:%M:%S")

    registrar_asistencia_airtable(
        cedula=cedula,
        nombre=nombre,
        area=area,
        charla=charla,
        fecha=fecha,
        hora=hora
    )

    try:
        registrar_asistencia_local_respaldo(
            cedula=cedula,
            nombre=nombre,
            area=area,
            charla=charla,
            fecha=fecha,
            hora=hora
        )
    except Exception:
        pass

    return ahora


@app.route("/", methods=["GET", "POST"])
def index():
    mensaje = ""
    tipo = ""

    if request.method == "POST":
        cedula = request.form["cedula"].strip()

        nombre, area, error = buscar_persona(cedula)

        if error:
            mensaje = error
            tipo = "error"
        else:
            charla, error_charla = buscar_charla_del_dia_por_area(area)

            if error_charla:
                mensaje = error_charla
                tipo = "error"
            else:
                try:
                    ahora = registrar_asistencia(cedula, nombre, area, charla)

                    mensaje = (
                        f"Asistencia registrada correctamente<br>"
                        f"<strong>Nombre:</strong> {nombre}<br>"
                        f"<strong>Cédula:</strong> {cedula}<br>"
                        f"<strong>Área:</strong> {area}<br>"
                        f"<strong>Charla:</strong> {charla}<br>"
                        f"<strong>Fecha:</strong> {ahora.strftime('%Y-%m-%d')}<br>"
                        f"<strong>Hora:</strong> {ahora.strftime('%H:%M:%S')}"
                    )
                    tipo = "exito"

                except Exception as e:
                    mensaje = f"No se pudo registrar en Airtable. Error: {e}"
                    tipo = "error"

    return render_template("index.html", mensaje=mensaje, tipo=tipo)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
