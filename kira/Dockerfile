FROM python:3.12-alpine

RUN \
  apk add --no-cache \
    bash \
    build-base \
  && python -m venv /opt/kira-venv

WORKDIR /opt/kira

COPY kira_app/ /opt/kira/
COPY requirements-addon.txt /opt/kira/requirements-addon.txt
COPY rootfs/ /

RUN \
  /opt/kira-venv/bin/python -m pip install --upgrade pip \
  && /opt/kira-venv/bin/python -m pip install -r /opt/kira/requirements-addon.txt \
  && /opt/kira-venv/bin/python -m pip install --no-deps -e /opt/kira \
  && chmod a+x /usr/local/bin/kira-run.sh \
  && chmod a+x /usr/local/bin/kira-options-to-env.py \
  && chmod a+x /usr/local/bin/kira-addon-preflight.py

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD /opt/kira-venv/bin/python -c "import json, urllib.request; data = json.load(urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3)); raise SystemExit(0 if data.get('ok') else 1)"

CMD ["/usr/local/bin/kira-run.sh"]
