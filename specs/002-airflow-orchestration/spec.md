# Especificación de Feature: Orquestación del Pipeline con Apache Airflow

**Rama del feature**: `002-airflow-orchestration`

**Creado**: 2026-10-11

**Estado**: Borrador

**Entrada**: Descripción del usuario: "Añadir Apache Airflow como orquestador del pipeline de aves de Nantes. Airflow correrá en una instancia EC2 pequeña (t3.small/medium) en eu-west-3. Un DAG diario (05:00 UTC) encadena: invocación de la Lambda de ingesta existente birds-inaturalist-ingestion (sin cambios en su código; el watermark sigue en SSM) → dbt run → dbt test de la arquitectura medallón (staging → intermediate → marts) sobre Athena, con cada modelo dbt como tarea visible (Astronomer Cosmos). Si una etapa falla, las siguientes no se ejecutan; reintentos automáticos y alertas en caso de fallo. La regla de EventBridge que hoy dispara la Lambda se desactiva para evitar doble ejecución. Disparo manual del DAG con parámetro full_refresh para backfill/re-ingesta completa. El refresco de Power BI se mantiene por horario (08:00 UTC) y queda fuera del alcance del DAG. Requiere enmienda MINOR de la constitución (1.0.0 → 1.1.0) para añadir Airflow al stack. Mantener coste operativo bajo y IAM de mínimo privilegio sin comodines."

## Contexto

Hoy el pipeline (feature `001-nantes-birds-pipeline`) se coordina solo por horario: EventBridge
dispara la ingesta a las 05:00 UTC y Power BI se actualiza a las 08:00 UTC. Ningún proceso
ejecuta las transformaciones dbt en producción: solo se ejecutan los tests en la CI de cada PR.
Este feature introduce un orquestador que encadena ingesta y transformación en un único flujo
diario con dependencias explícitas, reintentos, alertas e historial de ejecuciones.

## Escenarios de Usuario y Pruebas *(obligatorio)*

### Historia de Usuario 1 - Ejecución Diaria Encadenada de Ingesta y Transformación (Prioridad: P1)

Un ingeniero de datos necesita que cada día, sin intervención manual, se ingesten las
observaciones nuevas y se reconstruya el modelo dimensional, de modo que los datos estén listos
antes de la actualización programada de Power BI. Cada etapa solo debe empezar si la anterior
terminó correctamente.

**Por qué esta prioridad**: Cierra el hueco actual del pipeline: la transformación no está
automatizada en producción y las etapas no dependen unas de otras. Sin esto, el resto del
feature no aporta valor.

**Prueba Independiente**: Se puede probar disparando la ejecución diaria y verificando que la
ingesta termina, que a continuación se materializan los modelos de staging, intermedia y marts
en orden, que sus tests pasan y que la ejecución queda registrada como exitosa.

**Escenarios de Aceptación**:

1. **Dado** que llega la hora programada (05:00 UTC), **Cuando** el orquestador inicia la ejecución diaria, **Entonces** invoca la ingesta existente y, solo cuando esta termina con éxito, ejecuta las transformaciones en el orden staging → intermedia → marts.
2. **Dado** que la ingesta termina con éxito, **Cuando** se ejecutan las transformaciones, **Entonces** cada modelo se materializa y se valida con sus tests antes de que se construyan los modelos que dependen de él.
3. **Dado** que la ingesta no encuentra observaciones nuevas, **Cuando** termina, **Entonces** la ejecución continúa con las transformaciones igualmente y finaliza con éxito.
4. **Dado** que la ejecución diaria ha terminado, **Cuando** el ingeniero consulta la interfaz del orquestador, **Entonces** ve el estado, la duración y los logs de cada etapa y de cada modelo por separado.

---

### Historia de Usuario 2 - Contención de Fallos, Reintentos y Alertas (Prioridad: P2)

Un ingeniero de datos necesita que un fallo en cualquier etapa detenga las etapas posteriores,
que los fallos transitorios se reintenten automáticamente y que, si el fallo persiste, reciba
una alerta para actuar antes de que Power BI se actualice con datos incompletos.

**Por qué esta prioridad**: Evita promover datos parciales o inválidos y reduce el tiempo de
detección de problemas. Depende de que exista el flujo encadenado de la Historia 1.

**Prueba Independiente**: Se puede probar provocando un fallo en la ingesta y, por separado, un
fallo en un test de dbt, y verificando que las etapas posteriores no se ejecutan, que se
realizan los reintentos configurados y que llega una alerta al responsable.

**Escenarios de Aceptación**:

1. **Dado** que la ingesta falla, **Cuando** se agotan los reintentos, **Entonces** no se ejecuta ninguna transformación, la ejecución queda marcada como fallida y el responsable recibe una alerta.
2. **Dado** un error transitorio en una etapa, **Cuando** el orquestador la reintenta, **Entonces** la etapa se completa en un reintento posterior y la ejecución continúa sin intervención manual.
3. **Dado** que falla un test de un modelo, **Cuando** el orquestador lo detecta, **Entonces** no se construye ningún modelo que dependa de él y el responsable recibe una alerta que identifica el modelo y el test fallidos.
4. **Dado** que una ejecución falló, **Cuando** el ingeniero corrige la causa y relanza la ejecución, **Entonces** el pipeline alcanza un estado final correcto sin duplicados ni reparaciones manuales de datos.

---

### Historia de Usuario 3 - Reconstrucción Completa Bajo Demanda (Prioridad: P3)

Un ingeniero de datos necesita poder lanzar manualmente una ejecución de reconstrucción completa
(backfill) cuando cambia la lógica de un modelo o hay que recuperar datos históricos, sin
modificar el flujo diario ni ejecutar comandos a mano en distintos sistemas.

**Por qué esta prioridad**: Es una operación excepcional, pero la constitución exige que la
re-ingesta completa esté justificada y quede tras un disparo manual explícito.

**Prueba Independiente**: Se puede probar disparando manualmente la ejecución con la opción de
reconstrucción completa y verificando que las tablas incrementales se reconstruyen desde cero,
que los tests pasan y que no hay duplicados.

**Escenarios de Aceptación**:

1. **Dado** que el ingeniero dispara manualmente la ejecución con la opción de reconstrucción completa, **Cuando** se ejecutan las transformaciones, **Entonces** todos los modelos incrementales se reconstruyen desde cero.
2. **Dado** que se solicita una reconstrucción completa, **Cuando** se ejecuta la ingesta, **Entonces** la ingesta se comporta como en una ejecución normal (incremental según el watermark) y la reconstrucción se aplica solo a los modelos dbt, a partir de los datos raw ya existentes en S3; el watermark no se modifica.
3. **Dado** que hay una ejecución en curso, **Cuando** se dispara otra manualmente, **Entonces** la nueva espera a que termine la actual; nunca se ejecutan dos a la vez.

---

### Casos Límite

- ¿Qué ocurre si la instancia que aloja el orquestador está detenida o reiniciándose a la hora programada? Al recuperarse, se ejecuta una sola vez la ejecución pendiente más reciente, sin acumular ejecuciones atrasadas; el watermark garantiza que no se pierden observaciones.
- ¿Qué ocurre si la ejecución diaria todavía no ha terminado a las 08:00 UTC? Power BI se actualiza igualmente con los datos del día anterior; el retraso debe quedar visible y alertado.
- ¿Qué ocurre si la regla de EventBridge sigue activa por error junto al orquestador? La ingesta es idempotente, así que no habría duplicados, pero la ejecución doble debe evitarse desactivando la regla como parte del despliegue.
- ¿Qué ocurre si la Lambda devuelve un error de función pero la invocación técnica tiene éxito? El orquestador debe tratarlo como un fallo de la etapa, no como un éxito.
- ¿Qué ocurre si fallan las credenciales o permisos del orquestador hacia AWS? La etapa falla con un error identificable tras agotar los reintentos y se alerta al responsable.

## Requisitos *(obligatorio)*

### Requisitos Funcionales

- **FR-001**: El sistema DEBE ejecutar diariamente, a las 05:00 UTC, un flujo único que encadene la ingesta y la transformación del pipeline existente.
- **FR-002**: El flujo DEBE invocar la función de ingesta existente (`birds-inaturalist-ingestion`) sin modificar su código; el watermark incremental DEBE seguir gestionándose en SSM Parameter Store por la propia función.
- **FR-003**: El flujo DEBE tratar como fallo de la etapa de ingesta cualquier error devuelto por la función, aunque la invocación se haya realizado técnicamente.
- **FR-004**: Las transformaciones DEBEN ejecutarse solo después de una ingesta exitosa, respetando el orden de dependencias staging → intermedia → marts.
- **FR-005**: Cada modelo dbt DEBE aparecer como una tarea individual en el orquestador, con su propio estado, duración y logs, y sus tests DEBEN ejecutarse antes de construir los modelos que dependen de él.
- **FR-006**: Un fallo en cualquier etapa o test DEBE impedir la ejecución de todas las etapas y modelos dependientes.
- **FR-007**: Cada etapa DEBE reintentarse automáticamente ante fallos (por defecto 2 reintentos con 5 minutos de espera) antes de marcarse como fallida.
- **FR-008**: Ante un fallo definitivo de cualquier etapa, el sistema DEBE notificar por correo electrónico al responsable del pipeline, indicando la ejecución, la etapa y el error.
- **FR-009**: El sistema DEBE permitir disparar manualmente el flujo con una opción de reconstrucción completa que reconstruya desde cero los modelos dbt incrementales a partir de los datos raw existentes en S3. Esta opción NO DEBE modificar el watermark ni forzar una re-ingesta del histórico desde iNaturalist.
- **FR-010**: Nunca DEBE haber más de una ejecución del flujo activa a la vez; las ejecuciones adicionales DEBEN esperar.
- **FR-011**: Si se pierde una ejecución programada, el sistema DEBE ejecutar solo la más reciente al recuperarse, sin acumular ejecuciones atrasadas.
- **FR-012**: La regla de EventBridge que hoy dispara la ingesta DEBE desactivarse al poner en marcha el orquestador, de modo que exista un único programador activo.
- **FR-013**: El orquestador DEBE ejecutarse en una única instancia EC2 pequeña en `eu-west-3`, con todos sus componentes (programador, ejecución de tareas, interfaz web y base de metadatos) en esa instancia.
- **FR-014**: El rol IAM del orquestador DEBE limitarse a invocar esa única función Lambda y a los permisos de Athena, Glue y S3 que dbt necesita sobre los recursos del proyecto, sin ARNs comodín.
- **FR-015**: La interfaz web del orquestador NO DEBE estar expuesta públicamente a Internet; el acceso DEBE realizarse por un canal autenticado y restringido.
- **FR-016**: La actualización de Power BI DEBE mantenerse por horario (08:00 UTC) y queda fuera del flujo orquestado.
- **FR-017**: La constitución DEBE enmendarse a la versión 1.1.0 (MINOR) para incorporar Airflow al stack tecnológico antes de empezar la implementación.
- **FR-018**: La definición del flujo DEBE versionarse en el repositorio y validarse automáticamente (carga sin errores) en la CI.

### Entidades Clave

- **Flujo diario (DAG)**: Definición versionada del pipeline orquestado: programación, etapas, dependencias, reintentos y parámetros (reconstrucción completa).
- **Ejecución**: Una instancia del flujo con fecha lógica, tipo (programada o manual), parámetros, estado final y duración.
- **Etapa / Tarea**: Unidad ejecutable dentro de una ejecución (ingesta, o un modelo dbt con sus tests), con estado, intentos y logs.
- **Alerta**: Notificación enviada al responsable cuando una etapa falla de forma definitiva.

## Criterios de Éxito *(obligatorio)*

### Resultados Medibles

- **SC-001**: En días normales, los datos del día están ingestados, transformados y validados antes de las 07:00 UTC, con al menos una hora de margen respecto a la actualización de Power BI.
- **SC-002**: El 100 % de las ejecuciones en las que falla la ingesta o un test terminan sin ejecutar ninguna etapa dependiente.
- **SC-003**: El responsable recibe la alerta de un fallo definitivo en menos de 15 minutos desde que ocurre.
- **SC-004**: Un ingeniero puede identificar qué etapa o modelo falló, y por qué, en menos de 5 minutos desde la interfaz del orquestador, sin acceder a otros sistemas.
- **SC-005**: Ningún día se ejecuta la ingesta más de una vez de forma programada.
- **SC-006**: Una reconstrucción completa se lanza con una única acción manual y termina sin duplicados en ninguna capa.
- **SC-007**: El coste mensual adicional de la orquestación no supera los 25 USD.
- **SC-008**: Ninguna ejecución diaria requiere intervención manual para completarse cuando las fuentes y servicios están disponibles.

## Clarifications

### Session 2026-10-11

- Q: ¿La reconstrucción completa debe re-ingestar todo el histórico desde iNaturalist o solo reconstruir los modelos dbt a partir de los datos raw de S3? → A: Solo reconstruir los modelos dbt (`--full-refresh`) sobre los datos raw existentes; la Lambda, el watermark y el IAM no cambian. Una re-ingesta histórica sigue siendo una operación manual excepcional (borrar el parámetro SSM a mano).

## Supuestos

- Una re-ingesta completa del histórico desde iNaturalist queda fuera del flujo orquestado; si fuera necesaria, se hace manualmente borrando el parámetro `/birds-pipeline/last_successful_run_date`, como ya prevé la feature 001.

- La instancia EC2 funciona 24/7 (tipo t3.small, ampliable a t3.medium si la memoria no basta), con un coste estimado de 15–20 USD/mes más almacenamiento; detenerla fuera del horario de ejecución queda fuera de la v1.
- La base de metadatos del orquestador vive en la propia instancia; no se usa una base de datos gestionada para no añadir coste.
- Las alertas reutilizan el topic SNS `birds-pipeline-alerts` y el correo del responsable ya configurados en la feature 001; la alarma de CloudWatch sobre la Lambda se mantiene como respaldo.
- El acceso a la interfaz web se hará mediante AWS Systems Manager Session Manager o un túnel SSH, sin abrir puertos públicos.
- La Lambda de ingesta, los modelos dbt y sus tests de la feature 001 no cambian; este feature solo añade la capa de orquestación.
- La infraestructura de la instancia (red, rol IAM, grupo de seguridad) puede aprovisionarse con AWS CLI o Terraform; la elección se decide en el plan.
- La CI existente de dbt en GitHub Actions se mantiene y se amplía con la validación de la definición del flujo.
- La actualización de Power BI sigue programada a las 08:00 UTC en Power BI Service; dispararla desde el flujo queda para una versión futura.
