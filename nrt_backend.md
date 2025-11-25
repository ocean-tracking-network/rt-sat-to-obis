## Realtime plugin for PostgreSQL
1. Install and enable TimescaleDB extension 

```
# Enable contrib repository
sudo apt install postgresql-contrib


sudo sh -c "echo 'deb [signed-by=/usr/share/keyrings/timescaledb-archive-keyring.gpg] https://packagecloud.io/timescale/timescaledb/ubuntu/ jammy main' > /etc/apt/sources.list.d/timescaledb.list"

# Download and install the keyring
wget -O - https://packagecloud.io/timescale/timescaledb/gpgkey | gpg --dearmor | sudo tee /usr/share/keyrings/timescaledb-archive-keyring.gpg
# Update and install
sudo apt update
sudo apt install timescaledb-2-postgresql-14
```


2. Using existing docker image on Windows - Dock desktop

```
powershell
# Pull the image first (optional)
docker pull timescale/timescaledb:latest-pg14

docker run -d --name timescaledb -p 5432:5432 -e POSTGRES_PASSWORD=password timescale/timescaledb:latest-pg14
```

<img width="1699" height="905" alt="image" src="https://github.com/user-attachments/assets/b452fccb-065c-4e86-93d2-c97f075b8a71" />


3. In DBeaver create new connection: localhost_timescale according to the Docker image cridencials 


4. Enable timescaledb extesion:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

```

5. Create and test `hypertables`

```
CREATE TABLE conditions (
    time TIMESTAMPTZ NOT NULL,
    location TEXT NOT NULL,
    temperature DOUBLE PRECISION NULL
);

INSERT INTO conditions (time, location, temperature) VALUES
  (NOW() - INTERVAL '1 day', 'office', 22.5),
  (NOW() - INTERVAL '2 days', 'office', 23.1),
  (NOW() - INTERVAL '3 days', 'office', 21.8),
  (NOW() - INTERVAL '1 day', 'warehouse', 18.2),
  (NOW() - INTERVAL '2 days', 'warehouse', 17.9);

SELECT * FROM timescaledb_information.hypertables;
```
