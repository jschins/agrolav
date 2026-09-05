## Connect in SSMS

- Server name: `127.0.0.1,1433`
- Authentication: SQL Server Authentication
- Login: `sa`
- Password: the value of `MSSQL_SA_PASSWORD` in `hub/.env` (gitignored)
- Options → Connect to database: `agrolav`
- Options → Encryption: Mandatory, and tick Trust server certificate

## Start locally

1. Start the SQL Server Docker container.
2. Optional: connect SSMS as above.
3. PowerShell:

```powershell
cd C:\Coding\agrolav\hub
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& .venv\Scripts\Activate.ps1
uv sync
uv run hub
```

`HUB_DEV_LOGIN=1` in `hub/.env` lets country/center logins through on
loopback and writes nothing to `dbo.visitor_ip`. Do not copy that flag to
the server.
