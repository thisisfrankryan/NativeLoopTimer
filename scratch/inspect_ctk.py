import customtkinter

app = customtkinter.CTk()
frame = customtkinter.CTkScrollableFrame(app)
frame.pack()

print([attr for attr in dir(frame) if "canvas" in attr.lower() or "scroll" in attr.lower()])

app.destroy()
