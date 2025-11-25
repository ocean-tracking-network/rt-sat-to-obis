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
