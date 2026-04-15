from tkzs_config_service_client import ConfigServiceClient



if __name__ =='__main__':
    config_service = ConfigServiceClient()
    config_service.load_config_settings('all')