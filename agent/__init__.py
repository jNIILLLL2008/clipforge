"""The render agent.

PIPELINE_VERSION is the thing that matters here. The agent is a PyInstaller
build with the whole render pipeline compiled into it, so fixing the pipeline
on the server does nothing for anybody running an older .exe -- and since the
server now stands down for a live agent, an old .exe silently renders
everything.

That happened: a build from 17:42 kept producing videos with labels and edit
filtering from 17:42, hours after both were fixed and deployed, and nothing
anywhere said so.

Bump this whenever a change to backend/app/render or the source filters should
reach subscribers. The server compares it and tells the agent to update.
"""

__version__ = "1.4.0"

#: Raised when a render-affecting change ships. Compared against the server's
#: own number, which lives in backend/app/routes/agent.py.
PIPELINE_VERSION = 5
