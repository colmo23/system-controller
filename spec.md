A python tui application

It takes as input an ansible inventory file with a list of machine address
it also takes a config file with a list of unix services to be managed. For each service there can be a list of the files or commands of interest to that service.

On start up the TUI should ssh to each machine and get the systemctl status for all of the services of interest.
The main view of the TUI should be a list of the services. Each row should have service name, service status.
If you select a service you should get a new view with details of the service. The view should have "journalctl" output of the service and any files or command outputs for the service that are defined for that service in its config file.


