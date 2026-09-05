# Barabar in a container. The image installs nothing: the engine has zero runtime
# dependencies, the dataset is committed, and every model response is committed under
# llm_cache/ -- so this runs with no API key and no network.
#
# It is an interactive terminal program. Run it with -it or the exception browser has no
# terminal to read keys from and will print the list once and exit.
FROM python:3.12-slim

# The close is full of rupee signs and box-drawing characters. Without a UTF-8 locale the
# level bar renders as question marks, which is a bad first impression for a tool whose
# entire argument is made in a bar chart made of characters.
ENV LANG=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY . /app

# pytest and hypothesis are the only dependencies and only the test suite needs them, so they
# are not in the image. `make test` on a clone is where tests run.
ENTRYPOINT ["python", "-m", "tui"]
