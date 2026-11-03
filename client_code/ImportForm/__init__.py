from ._anvil_designer import ImportFormTemplate
from anvil import *
import anvil.server
import anvil.google.auth, anvil.google.drive
from anvil.google.drive import app_files
import anvil.users
import anvil.tables as tables
import anvil.tables.query as q
from anvil.tables import app_tables
import anvil.media
import time
import re
from anvil import Notification, confirm
from .. import Global
from .. import Function
from .. import FunctionsB

class ImportForm(ImportFormTemplate): 
  def __init__(self, **properties):
    # Set Form properties and Data Bindings.
    self.init_components(**properties)
    # Any code you write here will run before the form opens.
    self.Import_title.text = "Here you can import csv files for importing to the Database."
    Global.table_name = Global.action.split(" ")[1].lower()
    self.selected_table.text = Global.table_name

    Global.main_form.mb_left.visible = False
    Global.main_form.mb_middle.visible = False

    # Programmatically create and bind timer
    self.timer_1 = Timer(interval=0)
    self.timer_1.set_event_handler('tick', self.timer_1_tick)
    self.add_component(self.timer_1)
    
    self.active_task = None
    self.last_log_index = 0

    # save TableList self in Global.work_area
    Global.work_area[Global.current_work_area_name]["self"] = self
    # call refresh 
    FunctionsB.import_form_refresh(self)

  def upload_file_change(self, file, **event_args):
    """This method is called when a new file is loaded into this FileLoader"""
    # A file has been selected, confirm this with user and call server to start the import
    self.selected_file_name.text = ""
    self.message_log.text = ""
    self.import_progress_msg.text = ""
    Global.DBAcontrol = ""
    self.selected_file_name.text = "You have selected file: " + file.name
    msg = "You have selected file: " + file.name + "\nDo you wish to continue?"
    if confirm(content=msg):
      # 1. Start the background task 
      self.active_task = anvil.server.call("start_import_job", Global.table_name, file)
      # 2. Show a notification so the user knows processing is active
      self.import_progress_msg.text = ""
      # 3. Enable Timer component to poll every 1 second
      self.timer_1.interval = 1
  
    else:
      self.upload_file.clear()
      self.selected_file_name.text = ""
      self.message_log.text = ""
      self.import_progress_msg.text = ""
    pass

  def timer_1_tick(self, **event_args):
    """Fires every second while timer_1.interval == 1."""
    # When the user confirms the file to be imported, this timer function gets activated every second 
    # It gets information on the status of the import_file task and displays the progress
    
    if not self.active_task:
      self.timer_1.interval = 0
      return

    # Fetch active task state
    state = self.active_task.get_state()

    # Update percentage label
    progress = state.get('progress', 0)
    status_msg = state.get('status', 'Processing...')
    self.import_progress_msg.text = f"{status_msg} ({progress}%)."

    # Slice and append ONLY new log lines
    all_logs = state.get('logs', [])
    if len(all_logs) > self.last_log_index:
      new_logs = all_logs[self.last_log_index:]

      # Append new lines to TextArea
      self.message_log.text += "\n".join(new_logs) + "\n"

      # Update pointer index
      self.last_log_index = len(all_logs)

      # Auto-scroll to the latest log line
      Function.scroll_log_to_bottom(self.message_log)

    # Check if background task has finished
    if self.active_task.is_completed():
      # Stop timer polling loop
      self.timer_1.interval = 0
      
      # Re-fetch state & flush any final remaining log entries
      final_state = self.active_task.get_state()
      final_logs = final_state.get('logs', [])
      if len(final_logs) > self.last_log_index:
        remaining_logs = final_logs[self.last_log_index:]
        self.message_log.text += "\n".join(remaining_logs) + "\n"
        self.last_log_index = len(final_logs)
        Function.scroll_log_to_bottom(self.message_log)
        
      self.import_progress_msg.text += " Import file processing completed."
      # 4. Fetch the return message from the completed task
      msg = self.active_task.get_return_value()
      self.message_log.text += msg
      self.message_log.text += "--- FINISHED ---"
      # Auto-scroll to the latest log line
      Function.scroll_log_to_bottom(self.message_log)
    pass 

  def cancel_inserts_click(self, **event_args):
    """This method is called when the button is clicked"""
    #print(Global.DBAcontrol)
    message = anvil.server.call("delete_by_DBAcontrol",Global.DBAcontrol,Global.table_name)
    self.message_log.text += f"\nImport cancelled: {message}"
    byte_string = bytes(self.message_log.text, "utf-8")
    text_file = anvil.BlobMedia('text/plain', byte_string, name='Import_message.log')
    anvil.media.download(text_file)
    note = f"The import of records to table {Global.table_name} have been cancelled and any successfull inserts during the import process have been deleted from the table.\n{message}\nYou can check the downloaded log file for details."
    n = Notification(note)
    n.show()
    
    # update Site Summary
    Function.update_db_summary()
    pass

  def commit_inserts_click(self, **event_args):
    """This method is called when the button is clicked"""
    byte_string = bytes(self.message_log.text, "utf-8")
    logmsg_name = 'Import_message_' + Global.table_name + '.log'
    text_file = anvil.BlobMedia('text/plain', byte_string, name=logmsg_name)
    anvil.media.download(text_file)
    n = Notification(f"You selected to commit the successfull inserts to the table {Global.table_name}. You can check the downloaded log file for details.")
    n.show()
    
    # update Site Summary
    Function.update_db_summary()
    pass

  @handle("download_csv_template", "click")
  def download_csv_template_click(self, **event_args):
    """This method is called when the button is clicked"""
    # need to check when using this for a query dynamic table . Cannot use the describe_table call.
    # probably need other method to get columns position to pass on to create_csv
    if Global.table_name != "users":
      table_info = anvil.server.call("describe_table",Global.table_name)
      # create empty data_list with column heading and a col_list with table ordinal_position 
      data_list = {}
      col_order = {}
      for column in table_info:
        data_list[column["COLUMN_NAME"]] = None
        col_order[column["COLUMN_NAME"]] = column["ORDINAL_POSITION"]
      #print(data_list)
      csv_name = "Template_" + Global.table_name + ".csv"
    else:
      # table users is a special case (for the Anvil users DB table)
      data_list = {"email": None, "password": None, "systemrole": None, "initials": None, "firstname": None, "lastname": None}
      col_order = {"email": 1, "password": 2, "systemrole": 3, "initials": 4, "firstname": 5, "lastname": 6}
      csv_name = "Template_system_" + Global.table_name + ".csv"
    csv_file = anvil.server.call('create_csv',[data_list],[col_order],csv_name)
    anvil.media.download(csv_file)
    pass
