# Step 1: Use the Node.js 12 base image for development
FROM node:12 AS build

# Step 2: Set the working directory in the container
WORKDIR /app

# Step 3: Copy package.json and package-lock.json to the working directory
COPY package*.json ./

# Step 4: Install dependencies (usando --legacy-peer-deps para resolver conflictos)
RUN npm install --legacy-peer-deps

# Step 5: Copy the rest of the application files
COPY . .

# Step 6: Build the Angular application
RUN npm run build-prod

# Step 7: Use Nginx to serve the application
FROM nginx:stable-alpine AS production

# Step 8: Copy the build output from the previous stage to the Nginx HTML directory
COPY --from=build /app/dist/fuse /usr/share/nginx/html

# Step 9: Expose port 80
EXPOSE 80

# Step 10: Start Nginx server
CMD ["nginx", "-g", "daemon off;"]
