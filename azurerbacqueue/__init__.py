import logging
import os

import azure.functions as func
import requests
from azure.storage.blob import BlobServiceClient


def get_rest_api_token():
    try:
        oauth2_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        oauth2_body = {
            "client_id": os.environ["REST_CLIENT_ID"],
            "client_secret": os.environ["REST_CLIENT_SECRET"],
            "grant_type": "client_credentials",
            "resource": "https://management.azure.com",
        }
        oauth2_url = (
            f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/oauth2/token"
        )
        return requests.post(
            url=oauth2_url, headers=oauth2_headers, data=oauth2_body
        ).json()["access_token"]

    except Exception as e:
        logging.info(str(e))


def get_graph_api_token():
    try:
        oauth2_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        oauth2_body = {
            "client_id": os.environ["GRAPH_CLIENT_ID"],
            "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
        oauth2_url = f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/oauth2/v2.0/token"
        return requests.post(
            url=oauth2_url, headers=oauth2_headers, data=oauth2_body
        ).json()["access_token"]

    except Exception as e:
        logging.info(str(e))


def main(msg: func.ServiceBusMessage):
    # debugging start the function
    logging.info(
        "-------------------------------------------------------------------------------------"
    )
    logging.info(f"******* Generating weekly Azure rbac report *******")
    logging.info(
        f"Subscription Name: {(subscription := msg.get_body().decode('utf-8').split(','))[0]}"
    )
    logging.info(f"Subscription Id: {subscription[1]}")

    # constructing API headers and variables
    rest_api_headers = {
        "Authorization": f"Bearer {get_rest_api_token()}",
        "Content-Type": "application/json",
    }
    graph_api_headers = {
        "Authorization": f"Bearer {get_graph_api_token()}",
        "Host": "graph.microsoft.com",
    }
    logging.info(
        "-------------------------------------------------------------------------------------"
    )
    logging.info(f"******* Completed constructing API headers *******")

    # constructing rbacs and upns
    rest_api_url = f"https://management.azure.com/subscriptions/{subscription[1]}/providers/Microsoft.Authorization/roleAssignments?api-version=2015-07-01"
    rbacs = requests.get(url=rest_api_url, headers=rest_api_headers).json()["value"]
    logging.info(
        "-------------------------------------------------------------------------------------"
    )
    logging.info(f"******* Completed constructing RBACs *******")

    # constructing return UPNs and adding EXT upns to AAD Guest RBAC Review
    try:
        upns = "\n".join(
            requests.get(
                url=f"https://management.azure.com{rbac['properties']['roleDefinitionId']}?api-version=2015-07-01",
                headers=rest_api_headers,
            ).json()["properties"]["roleName"]
            + f" Role: {response.json()['userPrincipalName']} has been added to AAD Guest RBAC Review. "
            + str(
                requests.post(
                    url="https://graph.microsoft.com/v1.0/groups/c6f8666e-053a-4f09-a15c-6feee253af06/members/$ref",
                    headers=graph_api_headers,
                    json={
                        "@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{rbac['properties']['principalId']}"
                    },
                ).status_code
            )
            for rbac in rbacs
            if (
                response := requests.get(
                    url=f"https://graph.microsoft.com/v1.0/users/{rbac['properties']['principalId']}",
                    headers=graph_api_headers,
                )
            ).status_code
            == 200
            and "#EXT#" in response.json()["userPrincipalName"]
        )
        logging.info(
            (
                file_data := f"Subscription Name: {subscription[0]}\nSubscription Id: {subscription[1]}\nUPNs:\n{upns}\n\n\n\n"
            )
        )
        logging.info(
            "-------------------------------------------------------------------------------------"
        )
        logging.info(f"******* Completed constructing UPNs *******")

        # appending blob
        blob_service_client = BlobServiceClient.from_connection_string(
            os.environ["AZURERBAC_STORAGE_ACCOUNT_CONNECTION_STRING"]
        )
        blob_client = blob_service_client.get_blob_client(
            "rbacreport", "rbac_report.csv"
        )
        blob_client.append_block(file_data)

    except Exception as e:
        logging.info(str(e))
    logging.info(
        "-------------------------------------------------------------------------------------"
    )
    logging.info(f"******* Completed appending blob *******")
