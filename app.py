from flask import Flask, render_template, request
import pandas as pd
from datetime import datetime
import os

app = Flask(__name__)

CARPETA = r"C:\Users\MASTER\OneDrive\Documentos\Nueva carpeta"

ARCHIVO_BASE = os.path.join(CARPETA, "BASE DE DATOS CALIDAD Y TÉCNICO.csv")
ARCHIVO_ASISTENCIA = os.path.join(CARPETA, "REGISTRO_ASISTENCIA.csv")
ARCHIVO_CHARLAS = os.path.join(CARPETA, "CHARLAS.csv")


def leer_csv_seguro(ruta):
    try:
        return pd.read_csv(ruta, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(ruta, dtype=str, encoding="latin1")


def cargar_base_datos():
    df = leer_csv_seguro(ARCHIVO_BASE)
    df.columns = df.columns.str.strip()
    return df


def cargar_charlas():
    if not os.path.exists(ARCHIVO_CHARLAS):
        return None, f"No se encontró el archivo de charlas: {ARCHIVO_CHARLAS}"

    df = leer_csv_seguro(ARCHIVO_CHARLAS)
    df.columns = df.columns.str.strip()

    if "Fecha" not in df.columns:
        return None, "No se encontró la columna 'Fecha' en el archivo CHARLAS.csv."

    if "Charla" not in df.columns:
        return None, "No se encontró la columna 'Charla' en el archivo CHARLAS.csv."

    return df, None


def buscar_charla_del_dia():
    df, error = cargar_charlas()

    if error:
        return None, error

    fecha_actual = datetime.now().strftime("%Y-%m-%d")

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.strftime("%Y-%m-%d")

    resultado = df[df["Fecha"] == fecha_actual]

    if resultado.empty:
        return "Sin charla asignada", None

    charla = str(resultado.iloc[0]["Charla"]).strip()

    return charla, None


def buscar_persona(cedula):
    df = cargar_base_datos()

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


def registrar_asistencia(cedula, nombre, area, charla):
    ahora = datetime.now()

    nuevo_registro = pd.DataFrame([{
        "Cedula": cedula,
        "Nombre": nombre,
        "Area": area,
        "Charla": charla,
        "Fecha": ahora.strftime("%Y-%m-%d"),
        "Hora": ahora.strftime("%H:%M:%S")
    }])

    if os.path.exists(ARCHIVO_ASISTENCIA):
        asistencia = leer_csv_seguro(ARCHIVO_ASISTENCIA)
        asistencia = pd.concat([asistencia, nuevo_registro], ignore_index=True)
    else:
        asistencia = nuevo_registro

    asistencia.to_csv(ARCHIVO_ASISTENCIA, index=False, encoding="utf-8-sig")

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
            charla, error_charla = buscar_charla_del_dia()

            if error_charla:
                mensaje = error_charla
                tipo = "error"
            else:
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

    return render_template("index.html", mensaje=mensaje, tipo=tipo)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)