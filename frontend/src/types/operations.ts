export interface ProjectTask {
  id: string;
  name: string;
  status: string;
  risk?: string;
  assigned_to?: string;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  status: 'PLANNING' | 'ACTIVE' | 'ON_HOLD' | 'COMPLETED' | 'CANCELLED';
  progress: number;
  tasks: ProjectTask[];
}

export interface ResourceAllocation {
  id: string;
  name: string;
  type: string;
  allocated_hours: number;
  utilization: number;
}

export interface VendorContract {
  id: string;
  name: string;
  service: string;
  value: number;
  renewal?: string;
}

export interface PurchaseRequest {
  id: string;
  item: string;
  quantity: number;
  price: number;
  total: number;
  status: 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'ORDERED' | 'RECEIVED' | 'CANCELLED';
  requested_by?: string;
}

export interface Inspection {
  id: string;
  item: string;
  inspector: string;
  status: 'PASSED' | 'FAILED' | 'WARNING' | 'IN_PROGRESS';
  notes?: string;
}
