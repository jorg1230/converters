# Convertidor de Imagenes y Audio

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Tkinter](https://img.shields.io/badge/Interfaz-Tkinter-2F6F4E?style=for-the-badge)
![Licencia](https://img.shields.io/badge/Licencia-MIT-green?style=for-the-badge)

Aplicacion de escritorio para convertir archivos por lotes desde una interfaz simple. Permite elegir si vas a trabajar con imagenes o audio y despues muestra solo los formatos de salida compatibles.

## Caracteristicas

- Conversion por carpeta completa.
- Opcion para incluir subcarpetas.
- Salida en una carpeta nueva sin sobrescribir archivos existentes.
- Barra de progreso y registro de conversiones.
- Cancelacion durante el proceso.
- Arquitectura abierta para agregar nuevos tipos y formatos.
- FFmpeg incluido por dependencia de Python para conversiones de audio.

## Formatos Soportados

| Tipo | Entrada | Salida |
| --- | --- | --- |
| Imagen | `.heic`, `.heif`, `.jpg`, `.jpeg`, `.png`, `.webp`, `.tif`, `.tiff`, `.bmp` | `.png`, `.jpg` |
| Audio | `.wav`, `.mp3` | `.wav`, `.mp3` |

## Calidad

| Formato | Configuracion |
| --- | --- |
| PNG | Sin perdida, `compress_level=0`. |
| JPEG | Calidad maxima con `quality=100` y `subsampling=0`. JPEG siempre comprime con perdida. |
| WAV | PCM 24-bit, sin compresion con perdida adicional. |
| MP3 | `libmp3lame -q:a 0`, maxima calidad VBR. MP3 siempre comprime con perdida. |

## Requisitos

- Windows.
- Python 3.10 o superior.
- Conexion a internet la primera vez para instalar dependencias.

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Uso Rapido

Ejecuta la aplicacion con doble clic en:

```text
ejecutar_convertidor.bat
```

Tambien puedes abrirla desde PowerShell:

```powershell
python .\convertir_imagenes.py
```

En la ventana:

1. Selecciona la carpeta de entrada.
2. Selecciona la carpeta de salida o deja que la app cree una automaticamente.
3. Elige el tipo de archivo: `Imagen` o `Audio`.
4. Elige a que formato quieres convertir.
5. Marca `Incluir subcarpetas` si aplica.
6. Presiona `Convertir archivos`.

Por defecto, la carpeta de salida se crea junto a la original:

```text
<carpeta>_convertidas_<formato>
```

Ejemplo:

```text
fotos_convertidas_png
audios_convertidas_wav
```

## Crear Ejecutable

Para generar un `.exe`, ejecuta:

```text
crear_ejecutable.bat
```

El archivo se genera en:

```text
dist\ConvertidorImagenes.exe
```

## Arquitectura de Formatos

El proyecto esta preparado para crecer sin reescribir la interfaz. Los tipos y formatos se registran en `convertir_imagenes.py`.

### Tipos

`CONVERSION_KINDS` define los grupos visibles en la interfaz:

```python
CONVERSION_KINDS = (
    ConversionKind(key="image", label="Imagen", plural_label="imagenes"),
    ConversionKind(key="audio", label="Audio", plural_label="audios"),
)
```

### Formatos

`CONVERSION_FORMATS` define cada salida disponible:

```python
ConversionFormat(
    key="wav",
    label="WAV sin perdida adicional",
    kind="audio",
    input_extensions=frozenset(SUPPORTED_AUDIO_EXTENSIONS),
    output_suffix=".wav",
    converter=convert_to_wav,
)
```

Para agregar otro formato:

1. Crea una funcion convertidora que reciba `source` y `destination`.
2. Registra un nuevo `ConversionFormat`.
3. Si es un tipo nuevo, agrega antes una entrada en `CONVERSION_KINDS`.

## Dependencias

| Dependencia | Uso |
| --- | --- |
| Pillow | Lectura y escritura de imagenes. |
| pillow-heif | Soporte para HEIC/HEIF. |
| imageio-ffmpeg | FFmpeg embebido para audio. |

## Estructura

```text
convertidores/
|-- convertir_imagenes.py
|-- ejecutar_convertidor.bat
|-- crear_ejecutable.bat
|-- requirements.txt
|-- ConvertidorImagenes.spec
|-- README.md
`-- LICENSE
```

## Licencia

Este proyecto esta publicado bajo la licencia MIT. Puedes usarlo, copiarlo, modificarlo y distribuirlo libremente, incluso en proyectos personales o comerciales, siempre conservando el aviso de copyright y la licencia.

Consulta el archivo [LICENSE](LICENSE) para ver el texto completo.
