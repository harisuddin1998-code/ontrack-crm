#!/usr/bin/env python3
"""
Smart Data Extractor for SJ_MIS Database
Extracts REDO / Non-Reporting vehicle data from IRData, Vehicles, Clients, and gs_objects tables
"""
import sys
import os
import pyodbc
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# Fix Windows console UTF-8 output
if sys.platform == 'win32' and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ========== CONFIGURATION ==========
# Credentials come from the environment (see .env.example). Never hardcode them.
load_dotenv()

SERVER = os.environ["INTERNAL_DB_SERVER"]
USERNAME = os.environ["INTERNAL_DB_USER"]
PASSWORD = os.environ["INTERNAL_DB_PASSWORD"]
DATABASE = os.getenv("INTERNAL_DB_NAME", "SJ_MIS")

class SmartDataExtractor:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_folder = f"SMART_DATA_{self.timestamp}"
        
        os.makedirs(self.output_folder, exist_ok=True)
        print(f"\n[INFO] Output folder created: {self.output_folder}\n")
        
        # Define the 20 target fields
        self.target_fields = [
            'IR_ID', 'VehicleID', 'ClientID', 'RegNo', 'EngineNum', 'ChassisNum',
            'EmergencyMobile', 'EmergencyName', 'EmergencyPhone', 'EmergencyRelation',
            'ResPhone', 'SecondaryUser1', 'SecondaryUser2', 'SecondaryUser3', 'SecondaryUser4',
            'OfficePhone', 'IMEINo', 'SIMNo', 'UnitLocation', 'dt_tracker'
        ]
        
    def log(self, message, level="INFO"):
        """Display console output safely"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {
            "SUCCESS": "[OK]",
            "ERROR": "[ERROR]",
            "WARNING": "[WARN]",
            "INFO": "[INFO]",
            "DATA": "[DATA]",
            "HEADER": "[HEADER]"
        }.get(level, "[INFO]")
        
        print(f"[{timestamp}] {prefix} {message}")
    
    def connect(self):
        """Establish database connection - READ ONLY"""
        try:
            drivers = pyodbc.drivers()
            driver = None
            for d in ['ODBC Driver 18 for SQL Server', 'ODBC Driver 17 for SQL Server', 'SQL Server']:
                if d in drivers:
                    driver = d
                    break
            if not driver and drivers:
                driver = drivers[0]
            
            conn_string = f"DRIVER={{{driver}}};SERVER={SERVER};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD};Connection Timeout=30;"
            self.conn = pyodbc.connect(conn_string)
            self.cursor = self.conn.cursor()
            self.cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
            
            self.log(f"Connected to {DATABASE} on {SERVER} (READ-ONLY MODE)", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Connection failed: {e}", "ERROR")
            return False

    def extract_data(self):
        """Extract multi-table joined data matching exact column relationships"""
        if not self.conn:
            self.log("No database connection available", "ERROR")
            return pd.DataFrame()

        self.log("Extracting Joined Data from SJ_MIS...", "INFO")
        query = """
        SELECT
            ir.ID AS IR_ID,
            v.ID AS VehicleID,
            c.ID AS ClientID,
            v.RegNo,
            v.EngineNum,
            v.ChassisNum,
            COALESCE(c.EmergencyMobile, c.Cell1) AS EmergencyMobile,
            COALESCE(c.EmergencyName, c.Name) AS EmergencyName,
            COALESCE(c.EmergencyPhone, c.Cell2) AS EmergencyPhone,
            c.EmergencyRelation,
            COALESCE(c.ResPhone, c.Cell1) AS ResPhone,
            c.SecondaryUser1, c.SecondaryUser2, c.SecondaryUser3, c.SecondaryUser4,
            COALESCE(c.OfficePhone, c.Cell2) AS OfficePhone,
            COALESCE(ir.IMEINo, v.IMEINo, g.imei) AS IMEINo,
            COALESCE(ir.SIMNo, v.SIMNo) AS SIMNo,
            COALESCE(ir.UnitLocation, ir.InstallLocation, 'N/A') AS UnitLocation,
            g.dt_tracker,
            c.Name AS ClientName
        FROM Vehicles v WITH (NOLOCK)
        LEFT JOIN IRData ir WITH (NOLOCK) ON v.ID = ir.VehicleID
        LEFT JOIN Clients c WITH (NOLOCK) ON v.ClientID = c.ID OR ir.ClientID = c.ID
        LEFT JOIN gs_objects g WITH (NOLOCK) ON ir.IMEINo = g.imei OR v.IMEINo = g.imei
        WHERE (g.dt_tracker < DATEADD(HOUR, -24, GETDATE()) OR g.dt_tracker IS NULL)
          AND v.RegNo IS NOT NULL
          AND COALESCE(ir.IMEINo, v.IMEINo, g.imei) IS NOT NULL
          AND COALESCE(ir.IMEINo, v.IMEINo, g.imei) != 'Removed'
        """
        try:
            df = pd.read_sql(query, self.conn)
            self.log(f"Successfully extracted {len(df):,} records", "SUCCESS")
            
            # Clean string whitespace and format timestamps to PKT (GMT+5)
            if 'dt_tracker' in df.columns:
                df['dt_tracker'] = pd.to_datetime(df['dt_tracker'])
                df['dt_tracker_pkt'] = df['dt_tracker'].apply(lambda d: d + timedelta(hours=5) if pd.notnull(d) else None)
            
            for col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.strip().replace({'None': '', 'nan': '', 'N/A': '', 'Removed': ''})
                
            return df
        except Exception as e:
            self.log(f"Query execution failed: {e}", "ERROR")
            return pd.DataFrame()
        except Exception as e:
            self.log(f"Query execution failed: {e}", "ERROR")
            return pd.DataFrame()

    def save_to_excel_and_csv(self, final_df):
        """Save extracted data to Excel & CSV"""
        if final_df.empty:
            self.log("No data to save!", "WARNING")
            return
        
        csv_file = os.path.join(self.output_folder, "FINAL_DATA.csv")
        final_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        self.log(f"CSV saved: {csv_file}", "SUCCESS")
        
        excel_file = os.path.join(self.output_folder, "FINAL_DATA.xlsx")
        try:
            with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
                final_df.head(100000).to_excel(writer, sheet_name='NonReportingData', index=False)
            self.log(f"Excel saved: {excel_file}", "SUCCESS")
        except Exception as ex:
            self.log(f"Excel save notice: {ex}", "WARNING")

    def run(self):
        """Main execution"""
        self.log("="*60, "HEADER")
        self.log("SMART DATA EXTRACTION - SJ_MIS", "HEADER")
        self.log("="*60, "HEADER")
        
        if not self.connect():
            return False
            
        try:
            df = self.extract_data()
            if not df.empty:
                self.save_to_excel_and_csv(df)
                self.log(f"Extraction summary: {len(df):,} unique records retrieved.", "SUCCESS")
                return True
            else:
                self.log("No records retrieved from SJ_MIS.", "WARNING")
                return False
        except Exception as e:
            self.log(f"Extraction error: {e}", "ERROR")
            return False
        finally:
            if self.conn:
                self.conn.close()

if __name__ == "__main__":
    extractor = SmartDataExtractor()
    extractor.run()