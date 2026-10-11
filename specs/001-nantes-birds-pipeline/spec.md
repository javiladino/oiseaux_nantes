# Especificación de Feature: Pipeline Analítico de Biodiversidad en Nantes

**Rama del feature**: `001-nantes-birds-pipeline`

**Creado**: 2026-10-10

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Pipeline analítico end-to-end que ingesta observaciones de Aves en Nantes desde iNaturalist, las almacena en un Data Lake en S3, las transforma mediante dbt Core sobre AWS Athena a través de una arquitectura medallón (staging → intermedia → marts) y sirve un modelo dimensional en esquema estrella a Power BI."

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Ingesta Incremental de Observaciones (Prioridad: P1)

Un ingeniero de datos necesita tener disponibles en el Data Lake datos frescos de observaciones de aves cada día. El pipeline se ejecuta de forma programada, obtiene únicamente los registros nuevos de iNaturalist publicados desde la última ejecución exitosa para la región del Gran Nantes, y los almacena de forma duradera en formato JSON crudo sin ninguna transformación.

**Por qué esta prioridad**: Es la base de todo el pipeline. Sin una ingesta incremental confiable, ninguna transformación ni análisis posterior es posible. Es la primera porción vertical que entrega valor verificable de forma independiente.

**Prueba Independiente**: Se puede probar completamente disparando el job de ingesta y verificando que aparezcan nuevos archivos JSON en S3 bajo la partición de fecha correcta, que contengan únicamente registros creados después de la fecha de corte de la ejecución anterior, y que volver a ejecutar el job no genere archivos duplicados.

**Escenarios de Aceptación**:

1. **Dado** que el pipeline nunca ha sido ejecutado, **Cuando** se dispara el job de ingesta, **Entonces** todas las observaciones disponibles para el Gran Nantes son obtenidas y almacenadas como JSON en S3 particionado por año y mes.
2. **Dado** que existe una ejecución previa exitosa con una marca de tiempo de corte conocida, **Cuando** el job de ingesta se ejecuta nuevamente, **Entonces** solo se obtienen y almacenan las observaciones creadas después de ese corte.
3. **Dado** un error intermitente de la API durante la ingesta, **Cuando** el job es re-disparado, **Entonces** retoma desde el último estado exitoso y no genera registros duplicados.
4. **Dado** que la API devuelve cero observaciones nuevas, **Cuando** el job finaliza, **Entonces** no se escriben archivos y el estado previo se preserva.

---

### Historia de Usuario 2 - Transformación Analítica mediante Capas Medallón (Prioridad: P2)

Un ingeniero analítico necesita un modelo dimensional limpio y validado de observaciones de aves que pueda consultarse de forma eficiente. Ejecuta transformaciones dbt que promueven el JSON crudo a través de las capas de staging (aplanado y tipado), intermedia (validación geoespacial y enriquecimiento temporal) y marts (esquema estrella).

**Por qué esta prioridad**: El modelo dimensional es la interfaz entre los datos crudos ingestados y los insights de negocio. Sin él, Power BI no puede funcionar. Debe poder ejecutarse de forma independiente una vez que la ingesta ha sido exitosa.

**Prueba Independiente**: Se puede probar completamente ejecutando el DAG completo de dbt contra una capa raw poblada y verificando que `fct_observations`, `dim_species`, `dim_users` y `dim_date` se materialicen con tests de esquema de dbt aprobados y sin claves primarias duplicadas.

**Escenarios de Aceptación**:

1. **Dado** que hay archivos JSON crudos presentes en S3, **Cuando** se ejecuta el modelo de staging, **Entonces** las estructuras anidadas son aplanadas, las coordenadas son extraídas y las fechas se castean a timestamps UTC sin nulos en los campos requeridos.
2. **Dado** que el modelo de staging está poblado, **Cuando** se ejecuta el modelo intermedio, **Entonces** solo se conservan los registros cuyas coordenadas caen dentro del bounding box del Gran Nantes, y cada registro lleva la bandera `is_research_grade` y la clasificación `observation_period`.
3. **Dado** que el modelo intermedio está poblado, **Cuando** se ejecuta la capa de marts, **Entonces** `fct_observations` referencia claves válidas en las tres tablas de dimensiones, `dim_date` cubre el rango completo de fechas de observación y todos los tests de dbt pasan.
4. **Dado** que llega un registro con un valor de quality grade inválido, **Cuando** se ejecutan los tests de dbt, **Entonces** el test `accepted_values` falla y el pipeline no promueve el dato.
5. **Dado** que la capa de marts ya existe, **Cuando** se ejecuta el modelo incremental `fct_observations`, **Entonces** solo se agregan los registros nuevos y ningún registro existente se duplica.

---

### Historia de Usuario 3 - Insights de Biodiversidad en Power BI (Prioridad: P3)

Un analista de BI o investigador quiere explorar los patrones de observaciones de aves en Nantes — qué especies aparecen más, cuándo alcanzan su pico las migraciones y qué observadores son más activos — a través de dashboards interactivos sin necesidad de escribir SQL.

**Por qué esta prioridad**: Es el entregable final orientado al consumidor. Depende de que las historias 1 y 2 estén completas, pero es quien materializa el valor analítico completo del pipeline.

**Prueba Independiente**: Se puede probar completamente conectando Power BI a la capa de marts y confirmando que los tres visuales clave (mapa geoespacial, gráfico de tendencia estacional, tabla de ranking) se renderizan correctamente con datos reales y responden al filtrado cruzado.

**Escenarios de Aceptación**:

1. **Dado** que el modelo dimensional está poblado, **Cuando** un analista de BI abre el informe de Power BI, **Entonces** un mapa de Nantes muestra los puntos de observación geolocalizados filtrables por especie.
2. **Dado** que el informe está abierto, **Cuando** el analista selecciona un rango de fechas, **Entonces** el gráfico de distribución estacional se actualiza mostrando el recuento mensual de observaciones con etiquetas de estación biológica (primavera, verano, otoño, invierno).
3. **Dado** que el informe está abierto, **Cuando** el analista consulta el panel de ranking, **Entonces** se muestran las especies con mayor número de observaciones y los observadores más activos.
4. **Dado** que se han ingestado y transformado nuevos datos, **Cuando** el dataset de Power BI es actualizado, **Entonces** todas las métricas y visuales reflejan los registros más recientes sin intervención manual.

---

### Casos Límite

- ¿Qué ocurre cuando la API de iNaturalist devuelve observaciones con coordenadas ausentes o nulas?
- ¿Cómo gestiona el sistema una observación cuyas coordenadas caen exactamente en el límite del bounding box del Gran Nantes?
- ¿Qué ocurre si el mismo ID de observación aparece en dos ejecuciones de ingesta distintas (p. ej., solapamiento de paginación de la API)?
- ¿Cómo se comporta el pipeline si el bucket de S3 no está disponible durante la ingesta?
- ¿Qué ocurre cuando `common_name` está ausente para un taxón en la respuesta de la API?
- ¿Cómo gestiona `dim_date` las observaciones registradas antes del rango de calendario generado?

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El sistema DEBE extraer registros de observaciones de aves (Aves) de la API pública de iNaturalist acotados al bounding box geográfico del Gran Nantes.
- **FR-002**: El sistema DEBE ejecutarse de forma incremental, capturando únicamente las observaciones creadas o actualizadas después de la última ejecución de ingesta exitosa. La marca de tiempo de corte (watermark) DEBE persistirse en AWS SSM Parameter Store (un parámetro de tipo `String` por pipeline) y actualizarse atómicamente solo tras una ejecución exitosa. El rol IAM de Lambda DEBE incluir `ssm:GetParameter` y `ssm:PutParameter` únicamente sobre el ARN de ese parámetro.
- **FR-003**: El sistema DEBE preservar las respuestas crudas de la API exactamente como se reciben, sin transformación, en almacenamiento duradero de objetos particionado por año y mes.
- **FR-004**: El sistema DEBE aplanar las estructuras anidadas de las observaciones (coordenadas geoespaciales, campos taxonómicos, campos del observador) durante la transformación de staging.
- **FR-005**: El sistema DEBE validar que todos los registros de observaciones promovidos tengan coordenadas estrictamente dentro del bounding box geográfico del Gran Nantes.
- **FR-006**: El sistema DEBE clasificar cada observación por franja horaria en uno de cuatro períodos: Madrugada, Mañana, Tarde o Noche.
- **FR-007**: El sistema DEBE marcar cada observación con un booleano que indique si cumple los criterios de calidad de grado de investigación (research grade).
- **FR-008**: El sistema DEBE garantizar la unicidad de la clave primaria (`observation_id`) y rechazar los registros con clave primaria nula antes de su promoción a la capa analítica.
- **FR-009**: El sistema DEBE garantizar la integridad referencial entre la tabla de hechos y todas las tablas de dimensiones (`dim_species`, `dim_users`, `dim_date`).
- **FR-010**: El sistema DEBE validar los valores de `quality_grade` contra los tres valores aceptados: `research`, `needs_id` y `casual`.
- **FR-011**: El sistema DEBE generar una dimensión de calendario continua que cubra el rango completo de fechas de observación, enriquecida con estacionalidad biológica (primavera, verano, otoño, invierno).
- **FR-012**: El sistema DEBE exponer tres métricas analíticas a los consumidores de BI: recuento total de observaciones, recuento de especies distintas observadas y porcentaje de observaciones con grado de investigación.
- **FR-013**: El sistema DEBE soportar la visualización geoespacial de observaciones individuales en un mapa de Nantes, filtrable por especie.
- **FR-014**: Cualquier ejecución del job de ingesta o transformación DEBE ser idempotente — volver a ejecutarlo produce el mismo estado final sin crear duplicados.
- **FR-015**: Cada modelo dbt DEBE tener al menos un test de esquema documentado en su archivo de configuración `.yml` correspondiente.
- **FR-016**: El sistema DEBE emitir una alarma de CloudWatch sobre la métrica de errores/timeouts de Lambda. Dicha alarma DEBE estar conectada a un topic SNS que notifique por correo electrónico al responsable del pipeline. Los fallos de dbt en CI DEBE notificarlos GitHub Actions mediante el mecanismo de fallo de workflow nativo.

### Entidades Clave

- **Observación**: Un avistamiento de fauna verificado — el hecho central — que lleva una marca de tiempo, coordenadas geográficas, grado de calidad y vínculos con la especie y el observador.
- **Especie (Taxón)**: Una especie de ave con nombre científico, nombre común, rango taxonómico y estado de conservación (bandera de amenaza).
- **Observador (Usuario)**: Un científico ciudadano que envió la observación, identificado por su login y nombre de visualización.
- **Fecha**: Un día de calendario con atributos temporales (año, mes, trimestre, día de la semana) y una etiqueta de estación biológica.

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: Todas las nuevas observaciones de iNaturalist para el Gran Nantes están disponibles para consulta analítica dentro de las 24 horas posteriores a su publicación en la plataforma.
- **SC-002**: No existe ningún valor duplicado de `observation_id` en `fct_observations` en ningún momento.
- **SC-003**: El 100% de los registros en la capa de marts analítica se encuentran dentro de los límites geográficos del Gran Nantes.
- **SC-004**: Todos los tests de esquema de dbt pasan antes de que cualquier resultado de transformación sea promovido — un único fallo de test bloquea la promoción por completo.
- **SC-005**: Un analista de BI puede responder las tres preguntas analíticas clave (ranking de especies, distribución estacional, actividad de observadores) sin escribir SQL.
- **SC-006**: El pipeline puede ser re-ejecutado tras cualquier fallo y alcanzar un estado final correcto sin necesidad de eliminar registros ni reparar datos manualmente.
- **SC-007**: El coste operativo de ejecutar el pipeline completo (ingesta + transformación + almacenamiento) se mantiene cercano a cero para los volúmenes diarios típicos de datos de iNaturalist para Nantes.

## Clarifications

### Session 2026-10-10

- Q: ¿Dónde debe persistir Lambda el watermark de ingesta (marca de tiempo de la última ejecución exitosa)? → A: En SSM Parameter Store (parámetro `String` atómico, actualizado solo en caso de éxito; rol IAM de Lambda restringido al ARN de ese único parámetro).
- Q: ¿Power BI debe conectarse a Athena en modo Import o DirectQuery? → A: Modo Import con actualización programada diaria (alineada con la cadencia de ingesta; DirectQuery queda excluido de la v1 por su coste).
- Q: ¿Qué señal de observabilidad debe emitir el pipeline ante un fallo? → A: Alarma de CloudWatch sobre la métrica de errores/timeouts de Lambda → topic SNS → alerta por correo electrónico; los fallos de dbt en CI se notifican mediante el fallo del workflow de GitHub Actions.

## Supuestos

- La API pública de iNaturalist (`/v1/observations`) permanece accesible sin autenticación para el alcance y volumen requeridos.
- El bounding box geográfico (`swlat: 46.8600781, swlng: -2.6257395, nelat: 47.8359431, nelng: -0.9466615`) cubre completamente todas las áreas de observación relevantes en Nantes.
- La ingesta se ejecuta con cadencia diaria programada; la ingesta en tiempo real queda fuera del alcance.
- Power BI Desktop o Service está disponible para el consumidor de BI; no se requiere hosting de informes web ni embebido para la v1. El dataset de Power BI DEBE configurarse en modo **Import** con una actualización programada diaria (alineada con la cadencia de ingesta). DirectQuery sobre Athena queda explícitamente fuera del alcance de la v1 por su impacto en costes operativos.
- La infraestructura AWS (S3, Lambda, Athena, Glue, EventBridge) se aprovisionará por separado; esta spec cubre el comportamiento de los datos y las transformaciones, no la configuración de infraestructura.
- La re-ingesta completa de datos históricos (backfill) es una operación manual, disparada explícitamente — no forma parte del pipeline programado estándar.
- La ausencia de `common_name` en la respuesta de la API es aceptable; el campo será nulo en `dim_species` y el registro sigue siendo válido.
- Las observaciones con coordenadas ausentes o fuera de rango son descartadas en la capa intermedia y no se consideran pérdida de datos.
