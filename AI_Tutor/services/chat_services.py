class ChatService:

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def run_chat(
        self,
        query,
        selected_pdfs,
        uploaded_video_path=None,
        image_attachments=None
    ):

        result = self.orchestrator.run(

            query=query,

            selected_pdfs=selected_pdfs,

            uploaded_video_path=uploaded_video_path,

            image_attachments=image_attachments

        )

        return result