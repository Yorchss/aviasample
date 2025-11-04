import azure.functions as func
import logging
import azure.functions as func
import logging
import os
import json
from azure.cosmos import CosmosClient, exceptions

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Initialize Cosmos DB client
endpoint = os.environ["COSMOS_DB_ENDPOINT"]
key = os.environ["COSMOS_DB_KEY"]
database_id = os.environ["COSMOS_DB_DATABASE_ID"]
container_id = os.environ["COSMOS_DB_CONTAINER_ID"]

client = CosmosClient(endpoint, key)
database = client.get_database_client(database_id)
container = database.get_container_client(container_id)

@app.route(route="aviatrigger", methods=["GET", "POST", "PUT", "DELETE"])
def aviasample(req: func.HttpRequest) -> func.HttpResponse:
    logging.info(f"Processing {req.method} request.")

    try:
        if req.method == "GET":
            item_id = req.params.get("id")
            if not item_id:
                return func.HttpResponse("Missing 'id' parameter", status_code=400)
            item = container.read_item(item=item_id, partition_key=item_id)
            return func.HttpResponse(json.dumps(item), mimetype="application/json", status_code=200)

        elif req.method == "POST":
            body = req.get_json()
            if "id" not in body:
                return func.HttpResponse("Missing 'id' in request body", status_code=400)
            container.create_item(body)
            return func.HttpResponse("Item created", status_code=201)

        elif req.method == "PUT":
            body = req.get_json()
            item_id = body.get("id")
            if not item_id:
                return func.HttpResponse("Missing 'id' in request body", status_code=400)
            container.replace_item(item=item_id, body=body)
            return func.HttpResponse("Item updated", status_code=200)

        elif req.method == "DELETE":
            item_id = req.params.get("id")
            if not item_id:
                return func.HttpResponse("Missing 'id' parameter", status_code=400)
            container.delete_item(item=item_id, partition_key=item_id)
            return func.HttpResponse("Item deleted", status_code=200)

        else:
            return func.HttpResponse("Unsupported method", status_code=405)

    except exceptions.CosmosResourceNotFoundError:
        return func.HttpResponse("Item not found", status_code=404)
    except Exception as e:
        logging.error(f"Error: {e}")
        return func.HttpResponse(f"Internal server error: {str(e)}", status_code=500)