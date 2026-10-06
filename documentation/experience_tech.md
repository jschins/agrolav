# Which process holds port 8500

`sudo systemctl restart` stops the process the unit owns. It does not stop a `uvicorn` that was started outside that unit and is still listening.

On 6 October 2026 the Resultaat sheet still queried `dbo.mapping_banks` after `git reset`, `npm run build` in `balance/frontend` and `client/frontend`, and `sudo systemctl restart agrolav-hub agrolav-client agrolav-balance`. The builds refresh the browser files. They do not reload Python. The restart of `agrolav-balance` left `MainPID=0`. Port 8500 stayed with PID 631951, a root `uvicorn app.result_main:app` started on 5 October, which was not that unit's process. `kill` (SIGTERM) did not stop it. After that process was gone, `sudo systemctl restart agrolav-balance` bound port 8500 (MainPID 657135) and the sheet read `dbo.mapping`.

On 4 October 2026 the listener on 8500 was unit `agrolav-result.service` (`app.result_main:app`). `agrolav-balance` was `app.main:app` on port 8100. The unit files are on the server, not in this repo. `environment_tech.md` and `overview_tech.md` describe `agrolav-balance` as the process on 8500. Check the live listener before naming the restart.

```bash
pid=$(sudo ss -ltnp | sed -n 's/.*:8500 .*pid=\([0-9]*\).*/\1/p')
ps -ww -o pid,user,lstart,unit,cmd -p "$pid"
systemctl list-units 'agrolav-*' --no-pager
```

`ps aux` lists that listener among every other process. `unit` is `-` when systemd does not own it. Restart the unit named in that column. When the column is `-`, a restart of `agrolav-balance` cannot take the port until that process has exited.
