# Contrato: API v1 de iNaturalist — Endpoint de Observaciones

**Consumidor**: `ingestion/inaturalist_client.py` (Lambda)
**Proveedor**: API pública v1 de iNaturalist (sin autenticación)
**Fecha**: 2026-10-10

---

## Endpoint

```
GET https://api.inaturalist.org/v1/observations
```

## Cabeceras Obligatorias

```
User-Agent: oiseaux-nantes-pipeline/1.0 (contact: <pipeline-owner-email>)
Accept: application/json
```

La cabecera `User-Agent` es **obligatoria** según el principio II de la constitución (Ingesta
Ética de la API).

## Parámetros de Consulta (Ejecución Incremental)

| Parámetro | Tipo | Obligatorio | Ejemplo | Notas |
|-----------|------|-------------|---------|-------|
| `taxon_id` | integer | Sí | `3` | Clase Aves |
| `swlat` | float | Sí | `46.8600781` | Bounding box del Gran Nantes |
| `swlng` | float | Sí | `-2.6257395` | |
| `nelat` | float | Sí | `47.8359431` | |
| `nelng` | float | Sí | `-0.9466615` | |
| `created_d1` | string | Sí (incremental) | `2024-05-01T00:00:00` | ISO 8601; límite inferior sobre `created_at` |
| `created_d2` | string | Sí (incremental) | `2024-05-01T23:59:59` | ISO 8601; límite superior sobre `created_at` |
| `per_page` | integer | Sí | `200` | Valor máximo: 200 |
| `order_by` | string | Sí | `id` | Necesario para la estrategia de cursor `id_above` |
| `order` | string | Sí | `asc` | Orden ascendente por `id` |
| `id_above` | integer | No (primera página) | `123456` | Cursor para las páginas posteriores a la primera |

**Nota sobre `created_d1` en la primera ejecución**: Si no existe watermark, omitir
`created_d1`/`created_d2` para obtener todas las observaciones históricas.

## Estrategia de Paginación

Usar el cursor `id_above` (no paginación por páginas) para evitar el tope de 10.000 resultados:

```
1. Call with per_page=200, order_by=id, order=asc (no id_above)
2. Extract results[]; record max(id) as last_id
3. If len(results) < per_page → last page; stop
4. Else → call again with id_above=last_id; go to step 2
```

**Rate limit**: 1 petición por segundo (esperar 1 s entre llamadas).

## Esquema de Respuesta

```json
{
  "total_results": 1250,
  "page": 1,
  "per_page": 200,
  "results": [
    {
      "id": 123456,
      "created_at": "2024-05-01T10:23:00+00:00",
      "observed_on": "2024-04-30",
      "observed_time_zone": "Europe/Paris",
      "quality_grade": "research",
      "location": "47.2184,-1.5536",
      "positional_accuracy": 10,
      "taxon": {
        "id": 18793,
        "name": "Larus michahellis",
        "preferred_common_name": "Yellow-legged Gull",
        "rank": "species",
        "threatened": false
      },
      "user": {
        "id": 9876,
        "login": "birder42",
        "name": "Jane Birder"
      }
    }
  ]
}
```

## Contratos de Campo

| Ruta del campo | Tipo | Admite nulos | Restricción |
|----------------|------|--------------|-------------|
| `results[].id` | integer | No | Único por observación; usar como clave de deduplicación |
| `results[].created_at` | string | No | ISO 8601 con desfase horario |
| `results[].observed_on` | string | No | Formato `YYYY-MM-DD` |
| `results[].quality_grade` | string | No | Uno de: `research`, `needs_id`, `casual` |
| `results[].location` | string | Sí | Formato `"lat,lng"`; null si las coordenadas están ocultas |
| `results[].positional_accuracy` | integer | Sí | Metros |
| `results[].taxon.id` | integer | No | ID de taxón de iNaturalist |
| `results[].taxon.name` | string | No | Nombre científico |
| `results[].taxon.preferred_common_name` | string | Sí | Ausente en taxones poco comunes |
| `results[].taxon.rank` | string | No | Rango taxonómico |
| `results[].taxon.threatened` | boolean | No | Bandera de iNaturalist |
| `results[].user.id` | integer | No | ID de usuario de iNaturalist |
| `results[].user.login` | string | No | Nombre de usuario |
| `results[].user.name` | string | Sí | Nombre visible |

## Contrato de Gestión de Errores

| Estado HTTP | Significado | Comportamiento de Lambda |
|-------------|-------------|--------------------------|
| 200 | Éxito | Parsear y escribir en S3 |
| 429 | Rate limit alcanzado | Backoff exponencial + reintento (máx. 3 intentos) |
| 500/503 | Error de la API | Reintento con backoff; Lambda falla tras agotar los reintentos |
| Timeout | Problema de red | Reintento con backoff; Lambda falla tras agotar los reintentos |

Ante un fallo de Lambda: el watermark **NO** se actualiza; EventBridge reintenta en la siguiente
programación; la alarma de CloudWatch salta con la métrica de errores de Lambda.

## Contrato de Almacenamiento (Salida)

Cada archivo S3 escrito por Lambda:
- **Ruta**: `s3://{bucket}/raw/inaturalist/observations/year={YYYY}/month={MM}/{timestamp}.json`
- **Formato**: NDJSON — un objeto JSON por línea (cada elemento de `results[]` es una línea)
- **Contenido**: Objetos de respuesta de la API en crudo, exactamente como se reciben (sin transformación)
- **Codificación**: UTF-8
