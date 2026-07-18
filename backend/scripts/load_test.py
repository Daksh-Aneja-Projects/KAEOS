from locust import HttpUser, task, between, events

class KAEOSLoadTester(HttpUser):
    wait_time = between(1, 5)
    
    def on_start(self):
        # Using the standard admin auth bypass for testing (tenant_acme is the default tenant)
        # Note: Actual authentication should hit /api/v1/auth/login and extract the token.
        self.headers = {
            "Content-Type": "application/json"
        }
        
    @task(3)
    def hr_dashboard(self):
        self.client.get("/api/v1/hr/dashboard", headers=self.headers, name="HR Dashboard")
        
    @task(3)
    def sales_dashboard(self):
        self.client.get("/api/v1/sales/dashboard", headers=self.headers, name="Sales Dashboard")
        
    @task(2)
    def fetch_employees(self):
        self.client.get("/api/v1/hr/employees", headers=self.headers, name="List Employees")
        
    @task(1)
    def check_hitl_queue(self):
        self.client.get("/api/v1/hitl/pending", headers=self.headers, name="HITL Pending Queue")
        
    @task(1)
    def connector_health(self):
        with self.client.get("/api/v1/connectors", headers=self.headers, catch_response=True, name="List Connectors") as response:
            if response.status_code == 200:
                data = response.json()
                connectors = data.get("connectors", [])
                if len(connectors) > 0:
                    conn_id = connectors[0]["id"]
                    self.client.get(f"/api/v1/connectors/{conn_id}/health", headers=self.headers, name="Connector Health")

    @task(1)
    def fetch_event_logs(self):
        self.client.get("/api/v1/events/log", headers=self.headers, name="Event Logs")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("Starting KAEOS Load Test...")
    
@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("KAEOS Load Test Complete.")
