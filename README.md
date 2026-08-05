# Webspider
App to query a Website domain and extract all linked urls and domains 

## Install
```
git clone https://github.com/myridia/webspider.git
cd webspider
poetry install
```

## Usage
```
./main.py -d <domain> [-p http|https] [-w workers] [-s delay] [-b chrome|firefox|edge|requests]
```
- `-d` domain to crawl (default: `127.0.0.1`)
- `-p` protocol (default: `https`, falls back to `http` automatically)
- `-w` parallel workers (default: 5)
- `-s` delay in seconds between batches (default: 0.2)
- `-b` fetcher backend (default: `chrome`, use `requests` to avoid a browser)

Results (links, broken, external, graph.html) are written to `results/<domain>/`.
Run `./main.py -t requests -d <domain>` to verify fetching works without a browser.

## Test run
### Run Docker to simulate a nested website on local host 127.0.0.1
```
cd website/dockers/
docker-compose up -d
```

### Local Test Run ./main.py to access the docker website what runs on your local host 127.0.0.1
```
cd ../../
./main.py
```
