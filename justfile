test_image := "mockpod-test:latest"
bind_path := "/app/bind"

uv_cmd := "uv --color always"
uv_sync := uv_cmd + " sync --all-extras --all-groups"
pytest_cmd := uv_cmd + " run -- pytest -vvv --log-level DEBUG --color=yes"

container_run := "podman run --rm -v $(pwd):" + bind_path + ":Z --security-opt label=disable"


default:
    @just --list


# Build test container image
build:
    podman build -t {{test_image}} -f tests/Containerfile .

# Rebuild test container image from scratch
rebuild:
    podman build --no-cache -t {{test_image}} -f tests/Containerfile .

# Remove test container image
rm-image:
    podman image rm {{test_image}}

# Open interactive shell in test container
shell:
    {{container_run}} -ti {{test_image}} /bin/bash

# Run unit tests
test-unit *ARGS: build
    {{container_run}} {{test_image}} /bin/bash -c \
        "cd {{bind_path}} && {{uv_sync}} && {{pytest_cmd}} tests/unit {{ARGS}}"

# Run integration tests
test-integration *ARGS: build
    {{container_run}} --privileged {{test_image}} /bin/bash -c \
        "cd {{bind_path}} && {{uv_sync}} && {{pytest_cmd}} tests/integration {{ARGS}}"

# Run all tests
test *ARGS: build
    {{container_run}} --privileged {{test_image}} /bin/bash -c \
        "cd {{bind_path}} && {{uv_sync}} && {{pytest_cmd}} tests {{ARGS}}"
