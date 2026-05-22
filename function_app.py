import azure.functions as func
import logging
import os
import json
import azure.functions as func
import logging
import requests
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.functions import HttpRequest, HttpResponse
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

@app.route(route="aviatest", methods=["GET", "POST", "PUT", "DELETE"])
def aviatest(req: func.HttpRequest) -> func.HttpResponse:
    logging.info(f"Processing {req.method} request.")

    try:
        if req.method == "GET":
            item_id = req.params.get("id")
            if not item_id:
                return func.HttpResponse("Missing 'id' parameter", status_code=400)

            try:
                item = container.read_item(item=item_id, partition_key=item_id)
                return func.HttpResponse(json.dumps(item), mimetype="application/json", status_code=200)
            except exceptions.CosmosResourceNotFoundError:
                query = f"SELECT * FROM c WHERE c.id = '{item_id}'"
                items = list(container.query_items(query=query, enable_cross_partition_query=True))
                if items:
                    return func.HttpResponse(json.dumps(items[0]), mimetype="application/json", status_code=200)
                else:
                    return func.HttpResponse("Item not found", status_code=404)

        elif req.method == "POST":
            body = req.get_json()
            if not isinstance(body, dict) or "id" not in body:
                return func.HttpResponse("Missing or invalid 'id' in request body", status_code=400)

            try:
                container.create_item(body)
                return func.HttpResponse("Item created", status_code=201)
            except exceptions.CosmosResourceExistsError:
                return func.HttpResponse("Item already exists", status_code=409)

        elif req.method == "PUT":
            body = req.get_json()
            item_id = body.get("id")
            if not item_id:
                return func.HttpResponse("Missing 'id' in request body", status_code=400)

            query = f"SELECT * FROM c WHERE c.id = '{item_id}'"
            items = list(container.query_items(query=query, enable_cross_partition_query=True))
            if not items:
                return func.HttpResponse("Item not found", status_code=404)

            partition_key = items[0].get("categoryId", item_id)  # fallback if no categoryId
            container.replace_item(item=item_id, body=body, partition_key=partition_key)
            return func.HttpResponse("Item updated", status_code=200)

        elif req.method == "DELETE":
            item_id = req.params.get("id")
            if not item_id:
                return func.HttpResponse("Missing 'id' parameter", status_code=400)

            query = f"SELECT * FROM c WHERE c.id = '{item_id}'"
            items = list(container.query_items(query=query, enable_cross_partition_query=True))
            if not items:
                return func.HttpResponse("Item not found", status_code=404)

            partition_key = items[0].get("categoryId", item_id)
            container.delete_item(item=item_id, partition_key=partition_key)
            return func.HttpResponse("Item deleted", status_code=200)

        else:
            return func.HttpResponse("Unsupported method", status_code=405)

    except Exception as e:
        logging.error(f"Error: {e}")
        return func.HttpResponse(f"Internal server error: {str(e)}", status_code=500)


@app.function_name(name="ChatbotProxy")
@app.route(route="ChatbotProxy", methods=["POST"])
def chatbot_proxy(req: func.HttpRequest) -> func.HttpResponse:
    try:
        project = AIProjectClient(
            credential=DefaultAzureCredential(),
            endpoint="https://admin-1216-resource.services.ai.azure.com/api/projects/admin-1216"
        )

        agent = project.agents.get_agent("asst_SM8T7LKDvABBeND45Y1xh5iS")

        # ✅ Leer request
        data = req.get_json()
        logging.info(f"Request JSON: {data}")

        # ✅ NUEVO: manejar thread_id
        thread_id = data.get("thread_id")

        if not thread_id:
            # 🔵 Crear nuevo thread si no existe
            thread = project.agents.threads.create()
            thread_id = thread.id
            logging.info(f"Nuevo thread creado: {thread_id}")
        else:
            # 🟢 Reusar thread existente
            thread = project.agents.threads.get(thread_id)
            logging.info(f"Reusando thread: {thread_id}")

        # ✅ Crear mensaje del usuario
        project.agents.messages.create(
            thread_id=thread_id,
            role="user",
            content=data.get("message", "")
        )

        # ✅ Ejecutar agente
        run = project.agents.runs.create_and_process(
            thread_id=thread_id,
            agent_id=agent.id
        )

        if run.status == "failed":
            logging.error(f"Run failed: {run.last_error}")
            return func.HttpResponse(f"Run failed: {run.last_error}", status_code=500)

        # ✅ Obtener respuesta
        messages = project.agents.messages.list(thread_id=thread_id, order="asc")
        last_message = None

        for m in messages:
            if m.text_messages:
                last_message = m.text_messages[-1].text.value

        if not last_message:
            logging.warning("No hubo respuesta del agente")
            response = func.HttpResponse("No hubo respuesta del agente", status_code=200)
            response.headers["thread-id"] = thread_id
            return response

        # ✅ IMPORTANTE: devolver thread_id al frontend
        response = func.HttpResponse(last_message, status_code=200)
        response.headers["thread-id"] = thread_id

        return response

    except Exception as e:
        logging.error(f"Error en ChatbotProxy: {e}")
        return func.HttpResponse(str(e), status_code=500)

@app.function_name(name="ChatFrontendProxy")
@app.route(route="ChatFrontendProxy", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def chat_frontend_proxy(req: func.HttpRequest) -> func.HttpResponse:
    try:
        # Leer el mensaje del frontend
        data = req.get_json()

        # Recuperar el code desde variables de entorno
        code = os.environ["CHATBOT_CODE"]
        url = f"https://mchief.azurewebsites.net/api/ChatbotProxy?code={code}"

        # Reenviar la petición al chatbot original
        r = requests.post(url, json=data)

        # Devolver la respuesta y propagar el thread-id
        resp = func.HttpResponse(r.text, status_code=r.status_code)
        if "thread-id" in r.headers:
            resp.headers["thread-id"] = r.headers["thread-id"]

        return resp

    except Exception as e:
        logging.error(f"Error en ChatFrontendProxy: {e}")
        return func.HttpResponse(str(e), status_code=500)