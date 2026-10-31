# Why `HTTP 200` lies: seven ways a page was "unavailable" while every check was green

Gatewatch exists because of one long afternoon. A web service showed *"not available in your
country yet"* in the browser while `curl` through the same proxy chain returned **HTTP 200 and a
normal 812 KB page**, the proxy pool tested "healthy", and the watchdog stayed silent. These are the
causes we found, in the order they hid each other. Each one is now either prevented by design or
caught by `gatewatch check`.

| # | What was wrong | Why every check was green | What Gatewatch does about it |
|---|---|---|---|
| 1 | **The page was a stub, but the status was 200 and the size looked normal.** | Health checks looked at status code and size. | `check` judges the page *text* (configurable stub phrases, also `location=unsupported` in redirects) before it looks at size or status. |
| 2 | **The relay quietly sent traffic through a different exit** because a mode switch defaulted to it. | The relay answered, the page loaded, the proxy pool was healthy: nothing was "down". | The relay has **no silent fallback**. A dead exit means HTTP 502. `check` also proves the relay leaves through the *recorded* exit (the IP seen through the relay must equal the IP seen through the exit). |
| 3 | **The Chrome policy was ignored.** Written with `reg add` through a guest agent, the JSON lost its double quotes: `{ProxyMode:pac_script,...}`. | Nothing errors. Chrome just does not show the policy, and browses directly. | `Set-BrowserPac.ps1` and the Proxmox helper build the JSON with `ConvertTo-Json` and read it back. |
| 4 | **A proxy extension in the browser overrode the policy.** | The "my IP" page showed a foreign IP, which looked like success. | The docs tell you to open `chrome://policy` and to disable proxy extensions. |
| 5 | **Fail-open PAC.** `return "PROXY x; DIRECT"` means "if the relay is down, go direct", and direct is exactly the real IP that triggers the stub. | The page loads, with the stub. | The generated PAC returns only `PROXY relay` for the listed domains. A broken relay means a visible error, not a stub. |
| 6 | **Restart storms.** The upstream picker rewrote the config and restarted the proxy service every 10 minutes even when nothing changed, cutting every open stream. | Each restart "succeeded". | The exit is a file the relay re-reads when it changes. Switching never restarts anything, and `switch` does nothing when the current exit is fine. |
| 7 | **"Works through the proxy" was tested against an API endpoint, not the web page.** *(suspected, not confirmed in the original incident)* An API can be reachable from places where the web app is stubbed. | The pool tester used an API endpoint. | Pool nodes are judged by opening the **page you configure** with the same stub detection. Keep the upstream's location in mind anyway: see `docs/SECURITY.md`. |

Also worth knowing (suspected, not proven here): browsers keep HTTP/2 tunnels open for a long time, so
after a switch an already open tab can keep using the *old* exit. After changing the exit, restart the
browser or open an incognito window before judging the result.

## The rule behind all seven

> A green health check is a claim about the thing you measured, not about the thing you care about.
> Measure the user-visible page, and measure the *path*, not just the destination.
