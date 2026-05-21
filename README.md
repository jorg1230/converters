# Convertidor de imagenes y audio

Aplicacion grafica en Python para seleccionar una carpeta con archivos y crear otra carpeta con las conversiones.

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Uso

Ejecuta la aplicacion haciendo doble clic en:

```text
ejecutar_convertidor.bat
```

Para crear un ejecutable `.exe`, haz doble clic en:

```text
crear_ejecutable.bat
```

El ejecutable queda en:

```text
dist\ConvertidorImagenes.exe
```

Tambien puedes abrirla desde PowerShell:

```powershell
python .\convertir_imagenes.py
```

En la ventana puedes:

- Seleccionar la carpeta donde estan los archivos.
- Seleccionar la carpeta donde se van a guardar las conversiones.
- Elegir si vas a convertir imagenes o audio.
- Elegir el formato de salida disponible para ese tipo: PNG/JPEG para imagenes, WAV/MP3 para audio.
- Incluir subcarpetas si lo necesitas.
- Ver el avance con la barra de progreso.
- Cancelar la conversion antes de que termine.

Por defecto se crea una carpeta junto a la original con el nombre:

```text
<nombre_de_la_carpeta>_convertidas_png
```

## Calidad

- PNG guarda sin perdida de calidad.
- JPEG siempre comprime con perdida, pero este script usa `quality=100` y `subsampling=0` para conservar la mayor calidad posible.
- WAV se genera como PCM de 24 bits, sin compresion con perdida adicional.
- MP3 siempre comprime con perdida por definicion del formato, pero se genera con `libmp3lame -q:a 0`, la configuracion VBR de mayor calidad.

## Agregar formatos

El archivo `convertir_imagenes.py` usa una arquitectura abierta basada en `CONVERSION_FORMATS`.
Para sumar otro formato se agrega una funcion convertidora y un registro `ConversionFormat` con:

- `key`: identificador interno.
- `label`: texto visible en la interfaz.
- `kind`: tipo de archivo al que pertenece, por ejemplo `image` o `audio`.
- `input_extensions`: extensiones de entrada aceptadas.
- `output_suffix`: extension del archivo convertido.
- `converter`: funcion que recibe `source` y `destination`.

Si necesitas un tipo nuevo, por ejemplo video o documentos, primero agrega una entrada en `CONVERSION_KINDS` y luego registra sus formatos en `CONVERSION_FORMATS`.
