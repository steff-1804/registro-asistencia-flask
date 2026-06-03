from flask import Flask, render_template, request
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import unicodedata
import requests
from urllib.parse import quote

app = Flask(__name__)

# ==========================================================
# RUTAS DE ARCHIVOS
# ==========================================================

CARPETA = os.path.dirname(os.path.abspath(__file__))

ARCHIVO_BASE = os.path.join(CARPETA, "BASE DE DATOS CALIDAD Y TÉCNICO.csv")
ARCHIVO_CHARLAS = os.path.join(CARPETA, "CHARLAS.csv")
ARCHIVO_ASISTENCIA_LOCAL = os.path.join(CARPETA, "REGISTRO_ASISTENCIA.csv")

ZONA_HORARIA = ZoneInfo("America/Guayaquil")

# ==========================================================
# CONFIGURACIÓN AIRTABLE
# ==========================================================

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Asistencias")


# ==========================================================
# FUNCIONES GENERALES
# ==========================================================

def ahora_ecuador():
    return datetime.now(ZONA_HORARIA)


def normalizar_texto(texto):
    texto = str(texto).strip().upper()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto


def leer_csv_seguro(ruta):
    """
    Lee archivos CSV aunque estén separados por coma o punto y coma.

    IMPORTANTE:
    - Si tu CHARLAS.csv tiene comas dentro del nombre de la charla,
      lo más recomendable es guardar el CSV separado por punto y coma (;).
    - Esta función intenta detectar automáticamente el separador.
    """

    try:
        return pd.read_csv(
            ruta,
            dtype=str,
            encoding="utf-8-sig",
            sep=None,
            engine="python",
            on_bad_lines="skip"
        )
    except UnicodeDecodeError:
        return pd.read_csv(
            ruta,
            dtype=str,
            encoding="latin1",
            sep=None,
            engine="python",
            on_bad_lines="skip"
        )


def escapar_formula_airtable(texto):
    return str(texto).replace("'", "\\'")


# ==========================================================
# BASE DE PERSONAL
# ==========================================================

def cargar_base_datos():
    if not os.path.exists(ARCHIVO_BASE):
        raise FileNotFoundError(f"No se encontró el archivo base: {ARCHIVO_BASE}")

    df = leer_csv_seguro(ARCHIVO_BASE)
    df.columns = df.columns.str.strip()
    return df


def buscar_persona(cedula):
    try:
        df = cargar_base_datos()
    except Exception as e:
        return None, None, f"Error al cargar la base de datos: {e}"

    col_cedula = "CEDULA DE IDENTIDAD"
    col_nombre = "NOMBRES"
    col_area = "Area"

    columnas_requeridas = [col_cedula, col_nombre, col_area]

    for columna in columnas_requeridas:
        if columna not in df.columns:
            return None, None, f"No se encontró la columna: {columna}"

    df[col_cedula] = df[col_cedula].astype(str).str.strip()
    cedula = str(cedula).strip()

    resultado = df[df[col_cedula] == cedula]

    if resultado.empty:
        return None, None, "Cédula no encontrada en la base de datos."

    nombre = str(resultado.iloc[0][col_nombre]).strip()
    area = str(resultado.iloc[0][col_area]).strip()

    return nombre, area, None


# ==========================================================
# BASE DE CHARLAS
# ==========================================================

def cargar_charlas():
    if not os.path.exists(ARCHIVO_CHARLAS):
        return None, f"No se encontró el archivo de charlas: {ARCHIVO_CHARLAS}"

    try:
        df = leer_csv_seguro(ARCHIVO_CHARLAS)
    except Exception as e:
        return None, f"No se pudo leer CHARLAS.csv: {e}"

    df.columns = df.columns.str.strip()

    columnas_requeridas = ["Fecha", "Area", "Charla"]

    for columna in columnas_requeridas:
        if columna not in df.columns:
            return None, (
                f"No se encontró la columna '{columna}' en CHARLAS.csv. "
                f"Columnas encontradas: {list(df.columns)}"
            )

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.strftime("%Y-%m-%d")
    df["Area"] = df["Area"].astype(str).str.strip()
    df["Charla"] = df["Charla"].astype(str).str.strip()
    df["Area_Normalizada"] = df["Area"].apply(normalizar_texto)

    df = df.dropna(subset=["Fecha"])

    return df, None


def obtener_opciones_charlas():
    df, error = cargar_charlas()

    if error:
        print("ERROR CHARLAS:", error)
        return []

    opciones = []

    for _, fila in df.iterrows():
        fecha = str(fila["Fecha"]).strip()
        area = str(fila["Area"]).strip()
        charla = str(fila["Charla"]).strip()

        if (
            fecha
            and area
            and charla
            and charla.lower() != "nan"
            and area.lower() != "nan"
        ):
            opciones.append({
                "valor": f"{fecha}|||{area}|||{charla}",
                "texto": f"{fecha} - {area} - {charla}"
            })

    opciones.sort(key=lambda x: x["texto"])

    return opciones


def buscar_charla_del_dia_por_area(area_persona):
    df, error = cargar_charlas()

    if error:
        return None, error

    fecha_actual = ahora_ecuador().strftime("%Y-%m-%d")
    area_persona_normalizada = normalizar_texto(area_persona)

    resultado = df[
        (df["Fecha"] == fecha_actual) &
        (df["Area_Normalizada"] == area_persona_normalizada)
    ]

    if resultado.empty:
        return None, f"No se encontró una charla para hoy ({fecha_actual}) y el área {area_persona}."

    charla = str(resultado.iloc[0]["Charla"]).strip()

    return charla, None


def validar_charla_anterior(valor_charla, area_persona):
    try:
        fecha, area_charla, charla = valor_charla.split("|||")
    except ValueError:
        return None, None, "La charla seleccionada no es válida."

    if normalizar_texto(area_charla) != normalizar_texto(area_persona):
        return None, None, (
            f"La charla seleccionada pertenece al área {area_charla}, "
            f"pero la persona pertenece al área {area_persona}."
        )

    return fecha, charla, None


# ==========================================================
# AIRTABLE
# ==========================================================

def airtable_headers():
    if not AIRTABLE_TOKEN:
        raise ValueError("No se encontró AIRTABLE_TOKEN en Render.")

    if not AIRTABLE_BASE_ID:
        raise ValueError("No se encontró AIRTABLE_BASE_ID en Render.")

    return {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }


def airtable_url():
    tabla_codificada = quote(AIRTABLE_TABLE_NAME)
    return f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{tabla_codificada}"


def verificar_duplicado_airtable(cedula, fecha, charla):
    url = airtable_url()
    headers = airtable_headers()

    cedula_segura = escapar_formula_airtable(cedula)
    fecha_segura = escapar_formula_airtable(fecha)
    charla_segura = escapar_formula_airtable(charla)

    formula = (
        "AND("
        f"{{Cedula}}='{cedula_segura}',"
        f"DATETIME_FORMAT({{Fecha}}, 'YYYY-MM-DD')='{fecha_segura}',"
        f"{{Charla}}='{charla_segura}'"
        ")"
    )

    params = {"filterByFormula": formula}

    respuesta = requests.get(url, headers=headers, params=params, timeout=20)

    if respuesta.status_code != 200:
        raise Exception(
            f"Error verificando duplicados en Airtable: "
            f"{respuesta.status_code} - {respuesta.text}"
        )

    data = respuesta.json()
    registros = data.get("records", [])

    return len(registros) > 0


def registrar_asistencia_airtable(cedula, nombre, area, charla, fecha, hora, tipo_registro):
    if verificar_duplicado_airtable(cedula, fecha, charla):
        return False

    url = airtable_url()
    headers = airtable_headers()

    data = {
        "records": [
            {
                "fields": {
                    "Cedula": str(cedula),
                    "Nombre": str(nombre),
                    "Area": str(area),
                    "Charla": str(charla),
                    "Fecha": str(fecha),
                    "Hora": str(hora),
                    "TipoRegistro": str(tipo_registro)
                }
            }
        ],
        "typecast": True
    }

    respuesta = requests.post(url, headers=headers, json=data, timeout=20)

    if respuesta.status_code not in [200, 201]:
        raise Exception(f"Error de Airtable: {respuesta.status_code} - {respuesta.text}")

    return True


def registrar_asistencia_local_respaldo(cedula, nombre, area, charla, fecha, hora, tipo_registro):
    nuevo_registro = pd.DataFrame([{
        "Cedula": cedula,
        "Nombre": nombre,
        "Area": area,
        "Charla": charla,
        "Fecha": fecha,
        "Hora": hora,
        "TipoRegistro": tipo_registro
    }])

    if os.path.exists(ARCHIVO_ASISTENCIA_LOCAL):
        asistencia = leer_csv_seguro(ARCHIVO_ASISTENCIA_LOCAL)
        asistencia = pd.concat([asistencia, nuevo_registro], ignore_index=True)
    else:
        asistencia = nuevo_registro

    asistencia.to_csv(ARCHIVO_ASISTENCIA_LOCAL, index=False, encoding="utf-8-sig")


def registrar_asistencia(cedula, nombre, area, charla, fecha, tipo_registro):
    ahora = ahora_ecuador()
    hora = ahora.strftime("%H:%M:%S")

    creado = registrar_asistencia_airtable(
        cedula=cedula,
        nombre=nombre,
        area=area,
        charla=charla,
        fecha=fecha,
        hora=hora,
        tipo_registro=tipo_registro
    )

    if creado:
        try:
            registrar_asistencia_local_respaldo(
                cedula=cedula,
                nombre=nombre,
                area=area,
                charla=charla,
                fecha=fecha,
                hora=hora,
                tipo_registro=tipo_registro
            )
        except Exception:
            pass

    return creado, hora


# ==========================================================
# RUTA PRINCIPAL
# ==========================================================

@app.route("/", methods=["GET", "POST"])
def index():
    mensaje = ""
    tipo = ""

    opciones_charlas = obtener_opciones_charlas()

    if request.method == "POST":
        cedula = request.form.get("cedula", "").strip()
        modo_registro = request.form.get("modo_registro", "hoy").strip()

        nombre, area, error = buscar_persona(cedula)

        if error:
            mensaje = error
            tipo = "error"
            return render_template(
                "index.html",
                mensaje=mensaje,
                tipo=tipo,
                opciones_charlas=opciones_charlas
            )

        if modo_registro == "hoy":
            fecha = ahora_ecuador().strftime("%Y-%m-%d")
            charla, error_charla = buscar_charla_del_dia_por_area(area)

            if error_charla:
                mensaje = error_charla
                tipo = "error"
                return render_template(
                    "index.html",
                    mensaje=mensaje,
                    tipo=tipo,
                    opciones_charlas=opciones_charlas
                )

            tipo_registro = "Día actual"

        elif modo_registro == "anterior":
            valor_charla = request.form.get("charla_anterior", "").strip()

            if not valor_charla:
                mensaje = "Debe seleccionar la fecha y el tema de la asistencia anterior."
                tipo = "error"
                return render_template(
                    "index.html",
                    mensaje=mensaje,
                    tipo=tipo,
                    opciones_charlas=opciones_charlas
                )

            fecha, charla, error_charla = validar_charla_anterior(valor_charla, area)

            if error_charla:
                mensaje = error_charla
                tipo = "error"
                return render_template(
                    "index.html",
                    mensaje=mensaje,
                    tipo=tipo,
                    opciones_charlas=opciones_charlas
                )

            tipo_registro = "Día anterior"

        else:
            mensaje = "Tipo de registro no válido."
            tipo = "error"
            return render_template(
                "index.html",
                mensaje=mensaje,
                tipo=tipo,
                opciones_charlas=opciones_charlas
            )

        try:
            creado, hora = registrar_asistencia(
                cedula=cedula,
                nombre=nombre,
                area=area,
                charla=charla,
                fecha=fecha,
                tipo_registro=tipo_registro
            )

            if not creado:
                mensaje = (
                    f"Esta asistencia ya fue registrada anteriormente.<br>"
                    f"<strong>Nombre:</strong> {nombre}<br>"
                    f"<strong>Área:</strong> {area}<br>"
                    f"<strong>Charla:</strong> {charla}<br>"
                    f"<strong>Fecha:</strong> {fecha}"
                )
                tipo = "error"
            else:
                mensaje = (
                    f"Asistencia registrada correctamente<br>"
                    f"<strong>Nombre:</strong> {nombre}<br>"
                    f"<strong>Cédula:</strong> {cedula}<br>"
                    f"<strong>Área:</strong> {area}<br>"
                    f"<strong>Charla:</strong> {charla}<br>"
                    f"<strong>Fecha:</strong> {fecha}<br>"
                    f"<strong>Hora de registro:</strong> {hora}<br>"
                    f"<strong>Tipo:</strong> {tipo_registro}"
                )
                tipo = "exito"

        except Exception as e:
            mensaje = f"No se pudo registrar la asistencia. Error: {e}"
            tipo = "error"

    return render_template(
        "index.html",
        mensaje=mensaje,
        tipo=tipo,
        opciones_charlas=opciones_charlas
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
