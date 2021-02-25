import logging
import os

import azure.functions as func
import requests
from azure.storage.blob import BlobServiceClient


def get_graph_api_token():
    oauth2_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    oauth2_body = {
        "client_id": os.environ["GRAPH_CLIENT_ID"],
        "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }
    oauth2_url = (
        f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/oauth2/v2.0/token"
    )
    try:
        return requests.post(
            url=oauth2_url, headers=oauth2_headers, data=oauth2_body
        ).json()["access_token"]

    except requests.exceptions.RequestException as e:
        raise SystemExit(e)


def get_rest_api_token():
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
    try:
        return requests.post(
            url=oauth2_url, headers=oauth2_headers, data=oauth2_body
        ).json()["access_token"]

    except requests.exceptions.RequestException as e:
        raise SystemExit(e)


def get_azure_bill_table():
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            os.environ["AZBILL_STORAGE_ACCOUNT_CONNECTION_STRING"]
        )
        blob_client = blob_service_client.get_blob_client(
            "azurebilltable", "azurebilltable.csv"
        )
        return {
            (col := row.split(","))[0]: [
                float(col[1]),
                col[2],
                col[3],
                col[4],
                col[5],
                col[6],
            ]
            for row in blob_client.download_blob()
            .content_as_text(encoding="UTF-8")
            .splitlines()[1:]
        }
    except Exception as e:
        print(f"{e}")


def main(msg: func.ServiceBusMessage):
    # debugging start the function
    logging.info("-------------------------------------------------------------")
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
    azure_bill_table = get_azure_bill_table()
    logging.info("-------------------------------------------------------------")
    logging.info(f"******* Completed constructing API headers *******")

    # constructing rbacs and upns
    rest_api_url = f"https://management.azure.com/subscriptions/{subscription[1]}/providers/Microsoft.Authorization/roleAssignments?api-version=2015-07-01"
    rbacs = requests.get(url=rest_api_url, headers=rest_api_headers).json()["value"]
    logging.info("-------------------------------------------------------------")
    logging.info(f"******* Completed constructing RBACs *******")

    # constructing return UPNs and adding EXT upns to AAD Guest RBAC Review
    try:
        if subscription[0] in azure_bill_table:
            file_data = "\n".join(
                subscription[0]
                + f",{'Passthrough (Customer Self-Managed)' if azure_bill_table[subscription[0]][0] == 1.0 and azure_bill_table[subscription[0]][1] != 'Cenitex' else 'Passthrough (Cenitex Owned)' if azure_bill_table[subscription[0]][0] == 1.0 and azure_bill_table[subscription[0]][1] == 'Cenitex' else '25% (Cenitex Managed)' if azure_bill_table[subscription[0]][0] == 1.25 else '43.75% (Viccloudsafe Kofax)'}"
                + f",{azure_bill_table[subscription[0]][1]},{azure_bill_table[subscription[0]][3]},{azure_bill_table[subscription[0]][4]},{azure_bill_table[subscription[0]][5]},{response.json()['userPrincipalName'].split('#')[0]},{response.json()['displayName'].replace(',', '')},"
                + requests.get(
                    url=f"https://management.azure.com{rbac['properties']['roleDefinitionId']}?api-version=2015-07-01",
                    headers=rest_api_headers,
                ).json()["properties"]["roleName"]
                + ","
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
        else:
            file_data = "\n".join(
                f"{subscription[0]},,,,,,{response.json()['userPrincipalName'].split('#')[0]},{response.json()['displayName'].replace(',', '')},"
                + requests.get(
                    url=f"https://management.azure.com{rbac['properties']['roleDefinitionId']}?api-version=2015-07-01",
                    headers=rest_api_headers,
                ).json()["properties"]["roleName"]
                + ","
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
        logging.info(file_data)
        logging.info("-------------------------------------------------------------")
        logging.info(f"******* Completed constructing UPNs *******")
    except requests.exceptions.RequestException as e:
        raise SystemExit(e)

    # appending blob
    blob_service_client = BlobServiceClient.from_connection_string(
        os.environ["AZURERBAC_STORAGE_ACCOUNT_CONNECTION_STRING"]
    )
    blob_client = blob_service_client.get_blob_client("rbacreport", "rbac_report.csv")
    try:
        blob_client.append_block(f"{file_data}\n")

    except Exception as e:
        logging.info(str(e))
    logging.info("-------------------------------------------------------------")
    logging.info(f"******* Completed appending blob *******")
