"use client";

import { useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { DocumentIngestionRequest } from "@/lib/types";
import { Upload } from "lucide-react";

export function FileUpload() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [label, setLabel] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const supportedFormats = [".txt", ".md", ".pdf"];

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const fileName = file.name.toLowerCase();
    const isSupportedFormat = supportedFormats.some((fmt) =>
      fileName.endsWith(fmt)
    );

    if (!isSupportedFormat) {
      setMessage({
        type: "error",
        text: `Unsupported format. Supported: ${supportedFormats.join(", ")}`,
      });
      return;
    }

    setSelectedFile(file);
    setMessage(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) return;

    setIsLoading(true);
    setMessage(null);

    try {
      // Read file and convert to base64
      const reader = new FileReader();
      reader.onload = async (event) => {
        const base64Content = (event.target?.result as string).split(",")[1];

        const request: DocumentIngestionRequest = {
          source_type: "file",
          content: base64Content,
          filename: selectedFile.name,
          source_label: label || selectedFile.name,
        };

        try {
          const response = await apiClient.addDocuments(request);
          setMessage({
            type: "success",
            text: `✓ Uploaded and added ${response.chunks_created} chunks`,
          });
          setSelectedFile(null);
          setLabel("");
          if (fileInputRef.current) {
            fileInputRef.current.value = "";
          }
        } catch (error) {
          setMessage({
            type: "error",
            text:
              error instanceof Error ? error.message : "Failed to upload file",
          });
        } finally {
          setIsLoading(false);
        }
      };

      reader.readAsDataURL(selectedFile);
    } catch (error) {
      setMessage({
        type: "error",
        text: "Failed to read file",
      });
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Drag-and-drop zone */}
      <div
        className="border-2 border-dashed border-gray-600 rounded-lg p-6 text-center cursor-pointer hover:border-gray-400 hover:bg-gray-800/30 transition-colors"
        onClick={() => fileInputRef.current?.click()}
      >
        <Upload className="w-8 h-8 mx-auto text-gray-400 mb-2" />
        <p className="text-gray-300 font-medium">
          Drop a file or click to select
        </p>
        <p className="text-gray-400 text-sm">
          Supported: {supportedFormats.join(", ")}
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept={supportedFormats.join(",")}
          onChange={handleFileSelect}
          disabled={isLoading}
          className="hidden"
        />
      </div>

      {/* Selected file info */}
      {selectedFile && (
        <div className="bg-gray-800 p-3 rounded-lg">
          <p className="text-sm text-gray-300">
            <strong>Selected:</strong> {selectedFile.name}
          </p>
          <p className="text-xs text-gray-400">
            {(selectedFile.size / 1024).toFixed(2)} KB
          </p>
        </div>
      )}

      {/* Label */}
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">
          Label (optional)
        </label>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          disabled={isLoading}
          className="w-full bg-gray-700 text-white placeholder-gray-400 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          placeholder="e.g., Research Paper"
        />
      </div>

      {message && (
        <div
          className={`p-3 rounded-lg text-sm ${
            message.type === "success"
              ? "bg-green-500/20 text-green-300 border border-green-500/50"
              : "bg-red-500/20 text-red-300 border border-red-500/50"
          }`}
        >
          {message.text}
        </div>
      )}

      <button
        type="submit"
        disabled={!selectedFile || isLoading}
        className="w-full bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 disabled:opacity-50 text-white font-medium py-2 px-4 rounded-lg transition-colors"
      >
        {isLoading ? "Uploading..." : "Upload File"}
      </button>
    </form>
  );
}
