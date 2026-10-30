# Desplegar el broker Artemis de Lifeline en Azure

Guía preparada el 30 de octubre de 2026 para el proyecto actual.

Al terminar, el backend desplegado y el worker usarán el mismo broker de Azure.
El móvil seguirá llamando al backend por HTTPS.

```text
Móvil → Backend en Azure → Broker Artemis en VM Azure → Worker → Backend → Supabase
```

Esta guía despliega el broker en una VM Ubuntu con Docker. El worker seguirá en
la PC durante la prueba; la PC deberá permanecer encendida. El broker usa la
misma imagen `apache/activemq-artemis:2.40.0` del repositorio. Es una instalación
de una sola instancia: no proporciona alta disponibilidad.

## 1. Identificar los recursos y revisar el costo

Tu backend actual es:

```text
https://backend-lifeline-endwcsfcdtfqaaa2.canadacentral-01.azurewebsites.net
```

Prepara estos valores:

| Dato | Valor que debes guardar |
|---|---|
| App Service | `backend-lifeline` |
| Grupo existente del backend | `backend-emergentes` |
| VM nueva | `vm-lifeline-broker` |
| Grupo nuevo sugerido | `rg-lifeline-messaging` |
| Región sugerida | Canada Central, si tu suscripción tiene capacidad |
| Usuario de la VM | `azureuser` |
| IP pública de la VM | Se obtiene al crearla |
| FQDN del broker | Se obtiene en el paso 3 |

Como punto de partida para esta prueba, elige Linux x64 con 2 vCPU y 4 GiB de RAM
(por ejemplo, B2s si está disponible) y un disco administrado de 64 GiB. Ajusta
el tamaño según las opciones y cuotas de tu suscripción. El broker reservará
10 GiB de espacio libre.

Revisa la estimación del portal antes de crear recursos. VM, disco e IP pública
pueden generar cargos. No asumas que los créditos de estudiante cubren cualquier
recurso. Puedes estimarlo en la [calculadora de Azure](https://azure.microsoft.com/pricing/calculator/).
Crear los archivos de esta guía en tu PC no crea recursos ni genera cargos.

## 2. Crear la VM en el portal

1. Abre [Azure Portal](https://portal.azure.com/).
2. Busca **Virtual machines / Máquinas virtuales**.
3. Selecciona **Create → Azure virtual machine**.
4. Selecciona tu suscripción y crea el grupo `rg-lifeline-messaging`.
5. Escribe `vm-lifeline-broker` como nombre.
6. Selecciona **Ubuntu Server 24.04 LTS**, arquitectura **x64**.
7. Elige un tamaño con al menos 4 GiB de RAM para esta configuración.
8. En autenticación selecciona **SSH public key** y usuario `azureuser`.
9. Genera un par de claves y guarda el archivo `.pem` en tu PC.
10. En discos, selecciona un disco administrado de 64 GiB; Standard SSD sirve
    como punto de partida para esta prueba.
11. Crea una IP pública **Standard**, estática.
12. En puertos iniciales permite SSH; restringiremos el origen en el paso 4.
13. Revisa el precio y selecciona **Review + create → Create**.
14. Entra al recurso y copia su **Public IP address**.

Referencia: [creación de una VM Linux en el portal](https://learn.microsoft.com/azure/virtual-machines/linux/quick-create-portal?tabs=ubuntu).

## 3. Crear el nombre DNS del broker

1. Desde la VM, abre el recurso de su **Public IP address**.
2. Entra en **Configuration**.
3. En **DNS name label**, escribe un nombre disponible, por ejemplo
   `lifeline-broker-tuidentificador`.
4. Guarda y copia el **DNS name / FQDN exacto** que muestra Azure.

También puedes usar un dominio propio con un registro A hacia la IP pública.
Usa el FQDN exacto en el certificado y las conexiones; no construyas el nombre
suponiendo el formato, porque Azure puede añadir componentes al nombre.
Comprueba desde PowerShell:

```powershell
Resolve-DnsName TU_FQDN_REAL
```

Debe resolver a la IP pública de la VM. Sustituye `TU_FQDN_REAL` en los ejemplos
por el nombre que acabas de copiar, sin `https://` ni puerto.

Referencia: [nombres DNS e IP públicas de Azure](https://learn.microsoft.com/en-us/azure/virtual-network/ip-services/public-ip-addresses).

## 4. Configurar las reglas de red

Primero abre **App Services → backend-lifeline → Properties** o **Networking** y
copia las **Outbound IP addresses** y las **Additional/Possible outbound IP
addresses** disponibles. Debes permitir todas las IP de salida aplicables al
App Service; no uses su IP de entrada.

En la VM abre **Networking → Network settings → Network security group / Inbound
security rules**. Crea o ajusta estas reglas TCP:

| Puerto de destino | Origen permitido | Uso |
|---|---|---|
| 22 | Solo la IP pública de tu PC, `/32` | SSH |
| 80 | Internet | Validación y renovación del certificado HTTP-01 |
| 61617 | IP de salida del App Service y la IP pública de tu PC | Artemis con TLS |

Para 61617 puedes crear una regla para las IP del backend y otra para tu PC.
Si tu proveedor cambia la IP pública de tu PC, actualiza la regla del worker.
No publiques 61616 ni 8161 en el NSG: los ejemplos los enlazan solo a localhost
de la VM. La consola se abrirá mediante túnel SSH.

Las IP de salida pueden cambiar al modificar el plan o la infraestructura del
App Service. Si tu plan muestra salida **Dynamic**, configura una salida estable
(por ejemplo VNet/NAT) o revisa el plan antes de usar una lista fija. No abras
61617 a todo Internet como solución a un timeout.

Referencia: [direcciones de salida de App Service](https://learn.microsoft.com/en-us/azure/app-service/overview-inbound-outbound-ips).

## 5. Conectarte e instalar Docker

En PowerShell de tu PC, sustituye la ruta de la clave y la IP:

```powershell
ssh -i "C:\ruta\tu-clave.pem" azureuser@IP_PUBLICA_VM
```

Comprueba la huella SSH la primera vez con el valor de la VM. Desde este momento,
los bloques marcados `bash` se ejecutan **dentro de Ubuntu**, no en PowerShell.

Instala Docker usando su repositorio oficial en una VM nueva:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl openssl python3 certbot
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$(dpkg --print-architecture)" "$VERSION_CODENAME" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
```

Usaremos `sudo docker` para no modificar los grupos del usuario.
La restricción pública de los puertos se hace en el NSG; Docker puede eludir
reglas locales de UFW para puertos publicados.

Referencias: [SSH a la VM](https://learn.microsoft.com/en-us/azure/virtual-machines/linux-vm-connect),
[instalación de Docker en Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

## 6. Copiar los archivos de despliegue

Dentro de la VM:

```bash
sudo mkdir -p /opt/lifeline-broker
sudo chown "$USER:$(id -gn)" /opt/lifeline-broker
```

Abre **otra ventana de PowerShell en tu PC** y ejecuta, sustituyendo clave e IP:

```powershell
Set-Location "C:\Users\Usuario\Documents\EMERGENTES\Implementacion\lifeline-broker"
scp -i "C:\ruta\tu-clave.pem" azure/compose.yml azure/configure-broker.py azure/export-certificate.sh azure/renewal-hook.sh azureuser@IP_PUBLICA_VM:/opt/lifeline-broker/
```

Copia estos archivos, no la carpeta `instance` de tu PC. La VM generará una
instancia nueva con credenciales nuevas y sus propias colas. Los datos del broker
local no se migran con este procedimiento.

Vuelve a la terminal SSH:

```bash
cd /opt/lifeline-broker
chmod 700 export-certificate.sh renewal-hook.sh
sudo docker pull apache/activemq-artemis:2.40.0
```

Si un script muestra `sh\r` o `bash\r`, conviértelo a LF:

```bash
sed -i 's/\r$//' export-certificate.sh renewal-hook.sh configure-broker.py
```

## 7. Generar credenciales y crear la instancia

En la VM:

```bash
cd /opt/lifeline-broker
read -r -p 'FQDN real del broker: ' BROKER_FQDN
umask 077
printf 'ARTEMIS_USER=lifeline\nARTEMIS_PASSWORD=%s\nBROKER_KEYSTORE_PASSWORD=%s\nBROKER_FQDN=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" "$BROKER_FQDN" > .env
mkdir -p instance tls
BROKER_UID=$(sudo docker run --rm --entrypoint id apache/activemq-artemis:2.40.0 -u)
BROKER_GID=$(sudo docker run --rm --entrypoint id apache/activemq-artemis:2.40.0 -g)
sudo chown "$BROKER_UID:$BROKER_GID" instance tls
sudo docker compose -f compose.yml up -d
sudo docker compose -f compose.yml logs --tail 60 artemis
```

Espera a ver `Server is now active`. Después detén el broker para configurar TLS:

```bash
sudo docker compose -f compose.yml stop artemis
```

`.env` guarda el usuario, la contraseña del broker y una contraseña distinta para
su almacén TLS. Conserva este archivo de forma privada. No lo pegues en chats ni
lo subas a Git. No repitas la generación de `.env` sobre una instancia existente:
las credenciales de una instancia persistente no cambian solo por editar el
entorno de Docker.

`instance` contiene configuración y mensajes persistentes. Conservar esa carpeta
permite recrear el contenedor. No ejecutes `down -v`, no borres `instance` y no
copies datos de un broker en funcionamiento para simular un respaldo consistente.

Referencia: [persistencia y configuración de la imagen Artemis](https://artemis.apache.org/components/artemis/documentation/latest/docker.html).

## 8. Obtener el certificado y configurar TLS

En la misma VM, carga el nombre y solicita un certificado público:

```bash
cd /opt/lifeline-broker
set -a
source .env
set +a
sudo certbot certonly --standalone --preferred-challenges http --domain "$BROKER_FQDN"
```

Certbot pedirá correo y aceptación de condiciones. El DNS del paso 3 debe resolver
a la VM y el puerto TCP 80 debe estar accesible. HTTP-01 requiere ese puerto;
los clientes Artemis se conectarán por 61617.

Después:

```bash
sudo /opt/lifeline-broker/export-certificate.sh
sudo python3 configure-broker.py --xml instance/etc/broker.xml --env .env
sudo docker compose -f compose.yml up -d
sudo docker compose -f compose.yml logs --tail 80 artemis
```

El script agrega el acceptor CORE con TLS en 61617, crea las colas
`lifeline.case.jobs` y `lifeline.case.jobs.dlq`, configura reintentos y reserva
10 GiB libres. Guarda una copia inicial de `broker.xml` y no modifica los diarios
de mensajes.

El almacén `tls/broker.p12` contiene la clave privada del broker. Es distinto del
certificado raíz de Supabase, que corresponde a la conexión backend–base de datos.
Con este certificado de una CA pública, los clientes Java usan su almacén de
confianza habitual. Conserva la validación del nombre del servidor.

Comprueba TLS dentro de la VM:

```bash
openssl s_client -connect "$BROKER_FQDN:61617" -servername "$BROKER_FQDN" -verify_hostname "$BROKER_FQDN" -verify_return_error </dev/null
```

Debe terminar con `Verify return code: 0 (ok)`. Si el NSG no permite el acceso desde
la propia VM hacia su IP pública, prueba localmente manteniendo el nombre:

```bash
openssl s_client -connect 127.0.0.1:61617 -servername "$BROKER_FQDN" -verify_hostname "$BROKER_FQDN" -verify_return_error </dev/null
```

Referencias: [TLS de Artemis 2.40](https://artemis.apache.org/components/artemis/documentation/previous/2.40.0/configuring-transports.html),
[validación HTTP-01](https://letsencrypt.org/docs/challenge-types/).

## 9. Automatizar la renovación del certificado

Instala el hook y activa la renovación periódica:

```bash
sudo install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
sudo install -m 700 /opt/lifeline-broker/renewal-hook.sh /etc/letsencrypt/renewal-hooks/deploy/lifeline-broker
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

El hook vuelve a exportar el PKCS12 y reinicia Artemis cuando Certbot renueva un
certificado. Ese reinicio causa una interrupción breve; los clientes deberán
reconectarse. Mantén disponibles el DNS y el puerto 80 para las renovaciones.
Después de cambiar scripts o certificados, también puedes exportar y reiniciar
manualmente con los comandos del paso 8.

Referencia: [operación de Certbot](https://certbot.eff.org/instructions?ws=other&os=snap).

## 10. Conectar el backend de Azure

En **App Services → backend-lifeline → Settings → Environment variables → App
settings**, agrega o actualiza:

| Variable | Valor |
|---|---|
| `ARTEMIS_BROKER_URL` | `tcp://TU_FQDN_REAL:61617?sslEnabled=true&verifyHost=true` |
| `ARTEMIS_USER` | `lifeline` |
| `ARTEMIS_PASSWORD` | El valor generado en `.env` de la VM |
| `LIFELINE_OUTBOX_DESTINATION` | `lifeline.case.jobs` |

Reemplaza `TU_FQDN_REAL` por el nombre exacto del certificado. Pega los valores
sin comillas externas en el portal. Conserva las variables existentes de DB,
Cloudinary y JWT. Guarda/aplica: App Service reiniciará la aplicación.

No uses `127.0.0.1` ni el hostname del contenedor como dirección del broker remoto.
La URL es TCP con TLS; no es la URL de la consola web.

Desde tu PC puedes comprobar el puerto:

```powershell
Test-NetConnection TU_FQDN_REAL -Port 61617
```

Debe mostrar `TcpTestSucceeded: True` si la regla del NSG incluye tu IP actual.
Esto verifica conectividad TCP, no autenticación JMS; ambas se comprueban al
conectar el backend y el worker.

Referencias: [variables de App Service](https://learn.microsoft.com/en-us/azure/app-service/configure-common),
[direcciones de salida](https://learn.microsoft.com/en-us/azure/app-service/overview-inbound-outbound-ips).

## 11. Conectar el worker desde tu PC

Detén con **Ctrl+C**, en su terminal, el worker antiguo para evitar mantener dos
instancias con configuraciones distintas. Abre PowerShell en `lifeline-worker`:

```powershell
Set-Location "C:\Users\Usuario\Documents\EMERGENTES\Implementacion\lifeline-worker"
$env:ARTEMIS_BROKER_URL = 'tcp://TU_FQDN_REAL:61617?sslEnabled=true&verifyHost=true&consumerWindowSize=0'
$env:ARTEMIS_USER = 'lifeline'
$brokerSecret = Read-Host 'Contraseña ARTEMIS_PASSWORD generada en la VM' -AsSecureString
$env:ARTEMIS_PASSWORD = [System.Net.NetworkCredential]::new('', $brokerSecret).Password
$env:LIFELINE_BACKEND_URL = 'https://backend-lifeline-endwcsfcdtfqaaa2.canadacentral-01.azurewebsites.net'
$env:LIFELINE_WORKER_DESTINATION = 'lifeline.case.jobs'
$env:LIFELINE_WORKER_DEAD_LETTER_DESTINATION = 'lifeline.case.jobs.dlq'
$env:LIFELINE_WORKER_CONNECT_TIMEOUT = '10s'
$env:LIFELINE_WORKER_READ_TIMEOUT = '30s'
$jwtSecret = Read-Host 'JWT_SECRET actual del backend desplegado' -AsSecureString
$env:JWT_SECRET = [System.Net.NetworkCredential]::new('', $jwtSecret).Password
$env:JWT_ISSUER = 'lifeline'
java -jar .\target\lifeline-worker-0.0.1-SNAPSHOT.jar
```

Si cambiaste `JWT_ISSUER` en Azure, usa exactamente ese valor. `JWT_SECRET` debe ser
la misma clave Base64 del backend; no generes una distinta para el worker.
La clave del broker y la clave JWT cumplen funciones distintas.

Estas variables pertenecen a esa ventana de PowerShell. El worker actual no
importa automáticamente archivos `.env`. Si el JAR aún no existe, compílalo desde
esa carpeta con `.\mvnw.cmd -DskipTests package` antes de ejecutarlo.

En la VM, comprueba la cola sin imprimir la contraseña:

```bash
cd /opt/lifeline-broker
sudo docker compose -f compose.yml exec artemis sh -c 'exec /var/lib/artemis-instance/bin/artemis queue stat --url tcp://localhost:61616 --user "$ARTEMIS_USER" --password "$ARTEMIS_PASSWORD"'
```

`lifeline.case.jobs` debe mostrar al menos un consumidor. La conexión local de
administración dentro del contenedor usa 61616; las conexiones remotas usan TLS
por 61617. No debe repetirse `AMQ219007` ni el timeout de topología.

## 12. Abrir la consola por un túnel SSH

Desde otra PowerShell en tu PC:

```powershell
ssh -i "C:\ruta\tu-clave.pem" -L 18161:127.0.0.1:8161 azureuser@IP_PUBLICA_VM
```

Mantén la ventana abierta y visita [la consola local del túnel](http://127.0.0.1:18161/console).
Usa `lifeline` y la contraseña del broker. La consola no se publica directamente
en Internet. No uses `admin/admin` para esta instalación.

## 13. Comprobar el flujo completo desde el celular

1. Verifica que el backend terminó de reiniciar y responde.
2. Verifica el consumidor del paso 11.
3. En el móvil, inicia sesión contra el backend desplegado.
4. Crea una consulta con **solicitud de ayuda** y, si deseas, una foto.
5. Comprueba el envío confirmado y su `consultationId` en el backend.
6. Revisa la cola: debe subir el contador de mensajes recibidos y luego el de
   mensajes confirmados. En condiciones normales la cola vuelve a quedar vacía.
7. Revisa el worker: debe invocar el endpoint interno del backend desplegado sin
   errores 401/403 ni fallos de red.
8. Revisa `GET /api/v1/cases/me` con la sesión ciudadana, o la lista de casos del
   profesional aprobado. Debe existir un único caso para esa consulta.
9. Reintenta la misma consulta: la idempotencia debe evitar consultas y casos
   duplicados.
10. Asigna el caso, inicia la atención y ciérralo desde el flujo profesional.

El móvil no necesita la URL ni la contraseña de Artemis. Solo usa HTTPS al
backend. Las notificaciones push necesitan además la configuración de Firebase;
publicar el broker no sustituye esa configuración.

### Revisar trabajos antiguos que fallaron cuando el broker apuntaba a localhost

Antes de reintentar, confirma que la nueva conexión y las credenciales funcionan.
En Supabase SQL Editor puedes inspeccionar:

```sql
SELECT id, aggregate_id, status, attempts, next_attempt_at, published_at
FROM public.outbox_events
ORDER BY created_at DESC
LIMIT 30;
```

Si un evento quedó `FAILED`, identifica su UUID. Para volver a poner **solo ese
evento** en pendientes, sustituye el UUID y ejecuta:

```sql
UPDATE public.outbox_events
SET status = 'PENDING', attempts = 0,
    next_attempt_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
WHERE id = 'REEMPLAZAR_CON_UUID_DEL_EVENTO'::uuid
  AND status = 'FAILED'
RETURNING id, aggregate_id, status;
```

Un evento `PUBLISHED` no se reenvía con este comando. Si llegó a
`lifeline.case.jobs.dlq`, inspecciona el mensaje y su causa antes de reubicarlo.
No vacíes las colas ni actualices masivamente los eventos para probar.

## 14. Diagnóstico y operación

| Síntoma | Qué comprobar |
|---|---|
| `AMQ219007: Cannot connect` | DNS, VM encendida, NSG, puerto 61617 y URL TLS |
| `Timed out waiting to receive cluster topology` | Que 61617 realmente atienda CORE/TLS y el broker esté activo; no apunta a consola HTTP ni a AMQP 5672 |
| `SSLHandshakeException` / `PKIX` | Cadena completa, certificado vigente, reloj y CA de confianza del JDK; mantén `verifyHost=true` |
| Error de nombre del certificado | Usa el FQDN del certificado, no la IP pública |
| Autenticación JMS rechazada | Usuario/contraseña de la instancia persistente; cambiar `.env` no recrea sus usuarios |
| Worker sin consumidor | Worker detenido o conectado al broker antiguo |
| HTTP 401/403 al endpoint interno | `JWT_SECRET`, `JWT_ISSUER` y URL del backend en el worker |
| Cola crece sin confirmaciones | Disponibilidad del worker y respuestas del endpoint interno |
| Outbox `FAILED` y ningún mensaje nuevo | Corrige publicación y reintenta los eventos seleccionados del paso 13 |
| Broker bloquea productores por disco | Revisa `df -h` y conserva más de 10 GiB libres |
| `sh\r` / `bash\r` | Scripts con CRLF; conviértelos a LF |
| Firebase no entrega push | Revisar configuración y credenciales de Firebase por separado |

La VM inicia Docker al arrancar y Compose usa `restart: unless-stopped`.
Si detienes expresamente el contenedor, vuelve a levantarlo con `up -d`.
Mantén copias privadas de `.env`, la configuración y respaldos del disco. Para una
instantánea consistente del disco de esta prueba, detén brevemente Artemis,
crea la instantánea del disco administrado en Azure y vuelve a iniciarlo.
No guardes solo el contenedor: los mensajes están en `instance`.

Para pausar las pruebas, detén primero el worker y después el contenedor. En el
portal, detener y **desasignar** la VM detiene los cargos de cómputo; discos e IP
pueden seguir generando cargos. El backend acumulará o fallará publicaciones
mientras el broker esté apagado. Revisa el outbox al reanudar.

Referencia: [estados de una VM y facturación](https://learn.microsoft.com/azure/virtual-machines/states-billing).

## Archivos incluidos

| Archivo | Uso |
|---|---|
| `compose.yml` | Contenedor, persistencia, puertos y rotación de logs |
| `configure-broker.py` | Configuración TLS, colas y reserva de disco |
| `export-certificate.sh` | Conversión del certificado a PKCS12 |
| `renewal-hook.sh` | Renovación del almacén y reinicio del broker |
| `.env.example` | Referencia de nombres; genera secretos reales en la VM |

Estos archivos fueron preparados para el despliegue. No se ha creado una VM ni
se han modificado los recursos del App Service al generar esta guía.

Validación realizada: Compose analizado sin errores, configuración aplicada dos
veces sin duplicar el acceptor y conexión JMS por TLS a Artemis 2.40 en un
contenedor local aislado. La emisión pública del certificado y la conectividad
con tu nueva VM se verifican durante los pasos de despliegue.
