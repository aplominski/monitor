.PHONY: all build-front back run clean
all: build-front back

build-front:
	cd frontend && npm install --no-audit --no-fund && npm run build

back:
	rm -rf backend/static && cp -r frontend/dist backend/static

run:
	cd backend && uv run fastapi run --host 0.0.0.0 --port 8080

clean:
	rm -rf backend/static frontend/dist
