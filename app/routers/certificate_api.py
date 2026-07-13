import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import tempfile
from typing import List
from unittest import result

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import core


router = APIRouter()


@router.post("/generate_certificate")
async def generate_certificate( request: core.GenerateCertificateRequest, x_api_key: str = Header(None)):
    
    core.validate_api_key(x_api_key)


    farm_id = request.farm_id.strip()
    if not farm_id:
        raise HTTPException(status_code=400, detail="farmID is required")

    if "/" in farm_id:
        raise HTTPException(status_code=400, detail="farmID must not contain '/'")

    if not request.Device_Id:
        raise HTTPException(status_code=400, detail="DeviceIDS_list must not be empty")
     
    # check that the csr_pem is valid and matches the device_id
    core.validate_device_csr(
        csr_pem=request.csr_pem,
        device_id=request.Device_Id.strip(),
    )  
    # check that we have already asign the certificate to this  device or not 
    result = core.validate_device_IDS(request.Device_Id.strip()) 
    print(result)         

    if  "certificate_assigned" not  in result :
        raise HTTPException(status_code=400, detail=f"Server Error :- certificate_assigned key is missing in the result for this {request.Device_Id}")

    if result["certificate_assigned"] is None :
        raise HTTPException(
            status_code=400,
            detail=f"device_id {request.Device_Id} is not found in the database. Please check the device ID and try again."
        )  
      
    if result["certificate_assigned"] is True:
        raise HTTPException(
            status_code=400,
            detail=f"Certs are already generated on {result['certificate_assigned_at']} for this {request.Device_Id}"
        )    
    
    if result["certificate_assigned"] is False and request.dry_run is False:

        cert_data = core.generate_device_certificate_from_csr(
            csr_pem=request.csr_pem,
            device_id=request.Device_Id.strip(),
        )
        root_ca_key_pem, root_ca_pem = core.get_mqtt_ca_from_secrets_manager()

        is_valid = core.verify_generated_device_cert(
            device_crt_pem=cert_data["device_crt"],
            csr_pem=request.csr_pem,
            root_ca_pem=root_ca_pem,
            expected_device_id=request.Device_Id.strip(),
        )
        if is_valid:
            # upload to s3 and update the post sql then after successfully then reply .
            success = core.upload_device_crt_to_s3(farm_id, cert_data)

            if not success["success"]:
                raise HTTPException(status_code=500, detail="Failed to upload certificate to S3")
            
            update_result = core.update_certificate_assigned(request.Device_Id.strip())
            print(update_result)
            if update_result["success"] is False:
                raise HTTPException(status_code=500, detail="Failed to update certificate assignment in the database")
            
        return {
            "success": True,
            "device_id": request.Device_Id.strip(),
            "device_crt": cert_data["device_crt"]
        }
    
    if result["certificate_assigned"] is False and request.dry_run is True:
        return {
            "success": True,
            "dry_run": True,
            "device_id": request.Device_Id.strip(),
            "message": "CSR is valid and certificate can be generated."
        }

    





