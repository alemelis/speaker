## Pain points

- The FOMO ecosystem is made of different parts running on a mix of tmux and docker. 
- Three different pages to download, edit tags, and edit metadata.

## What we want

- Replace tmux+streamlit with docker+FastAPI+HTML/JS for the download page.
- A single landing page to access download and edit pages.
- Consistent styling across them all.

## Constraints

- Minimise the number of docker containers
- Minimise footprint of the system
- No JS frameworks

## Stretch

- Refactor folders so that everything is in a `fomo` root folder with components in subfolders.
- A single docker compose up should spin up everything
