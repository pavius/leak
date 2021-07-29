.PHONY: container-image
container-image:
	docker buildx build --platform linux/armhf -f Dockerfile -t leak:latest .

default: container-image