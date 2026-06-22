# Career_SecondBrain

## NAS Docker Deployment Notes

This repository is developed locally and pushed to GitHub. A sanitized working copy can also be synced to the Synology NAS for Docker-based services.

Current local paths:
- Local repo: `/Users/erathiachia/GitHub/Career_SecondBrain`
- NAS mount: `/Volumes/homes/Erathia`
- NAS Docker mirror: `/Volumes/docker/Career_SecondBrain`

Do not sync secrets or machine-local artifacts:
- `.env`, `.env.*`
- real `config.yaml` files
- `.venv/`, `node_modules/`, `dist/`
- caches, `.DS_Store`, `*.tsbuildinfo`, `*.tar.gz`

Dry-run sync before deploying:
```sh
rsync -avhn --delete \
  --exclude ".git/" \
  --exclude ".env" \
  --exclude ".env.*" \
  --exclude "config.yaml" \
  --exclude ".venv/" \
  --exclude "node_modules/" \
  --exclude "__pycache__/" \
  --exclude ".pytest_cache/" \
  --exclude "dist/" \
  --exclude ".DS_Store" \
  --exclude "*.tsbuildinfo" \
  --exclude "*.tar.gz" \
  /Users/erathiachia/GitHub/Career_SecondBrain/ \
  /Volumes/homes/Erathia/Career/Career_SecondBrain/